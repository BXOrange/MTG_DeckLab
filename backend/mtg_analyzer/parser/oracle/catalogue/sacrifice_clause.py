"""The object grammar of a "Sacrifice <things>" activation-cost clause (PAR-232, RULE 701.17 / 602.2b).

`cost_text`'s single-word recognizers read "Sacrifice a creature", "Sacrifice a Swamp and a Forest" and
"Sacrifice two lands"; this module reads everything wider with one shared item grammar: a list of distinct
objects ("a green creature, a white creature, and a blue creature"), the source among them ("~ and another green
creature", "2 lands and ~"), a union that distributes ("a black or artifact creature"), a multi-word subtype ("an
Eldrazi Scion"), and the tails "named X" / "named ~", "of the chosen type", "with a <kind> counter on it",
"attached to ~".

The result is a `SacrificeClause`; `game/costs.py` maps its items onto `ActivationCost` fields and the engine
matches each item's *word* (the `continuous.matches_permanent_word` encoding, extended with the tail tokens
``named:<name>``, ``chosentype``, ``counter:<kind>`` and ``attached``). Any word outside the shared card-type /
colour / subtype vocabulary makes the whole clause unreadable, so the ability stays unclaimed instead of being
charged cheaper than printed.

Pure -- **no `game/` imports** (front-end security boundary, docs/09).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from .subtype_vocabulary import SUBTYPES

#: Main card types a sacrificed permanent may be named by (RULE 300.1 permanent types, plus "permanent").
_TYPE_WORDS: frozenset[str] = frozenset({
    "artifact", "creature", "enchantment", "land", "planeswalker", "battle", "permanent",
})
#: Adjectives that narrow a permanent phrase without being a noun: colours (RULE 105.1), supertypes (RULE 205.4a),
#: the token / tapped state words. Mirrors `cost_text._QUALIFIER` (kept separate so this module stays import-light).
_ADJECTIVES: frozenset[str] = frozenset({
    "white", "blue", "black", "red", "green", "colorless", "multicolored", "nontoken", "nonland", "noncreature",
    "nonartifact", "nonenchantment", "basic", "snow", "legendary", "untapped", "tapped",
})
#: The token noun ("blood tokens", "an artifact token"): a permanent that is a token (RULE 111.1).
_TOKEN_WORD = "token"
#: Number words a count item may print; "a"/"an"/"another" are the singular determiners instead.
_COUNT_WORDS: dict[str, int] = {
    "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}
#: Marker the item's count carries when it is the announced X (RULE 107.3 / 601.2b).
COUNT_X = None

#: Tail tokens appended to a phrase's word; `continuous.matches_permanent_word` reads each one.
NAMED_PREFIX = "named:"
CHOSEN_TYPE_TOKEN = "chosentype"
COUNTER_PREFIX = "counter:"
ATTACHED_TOKEN = "attached"

_SELF_RE = re.compile(r"^(?:~|this\s+\w+|it)$")
_DETERMINER_RE = re.compile(
    r"^(?P<det>an?|another|x|\d+|" + "|".join(_COUNT_WORDS) + r")\s+(?P<phrase>.+)$"
)
#: Item separators inside a list: a comma (with an optional "and"), or a bare "and" followed by a new item.
_SEPARATOR_RE = re.compile(r",\s*(?:and\s+)?|\s+and\s+(?=(?:(?:an?|another|x|\d+|this|it|" + "|".join(_COUNT_WORDS) + r")\b|~))")
_VERB_RE = re.compile(r"\bsacrifice\s+")
#: A tail of an object phrase, peeled from the end (order is irrelevant; each is tried until none applies).
_TAIL_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\s+you control$"), ""),
    (re.compile(r"\s+of the chosen type$"), CHOSEN_TYPE_TOKEN),
    (re.compile(r"\s+attached to ~$"), ATTACHED_TOKEN),
    (re.compile(r"\s+with an?\s+(?P<kind>[+\-]?\d+/[+\-]?\d+|[a-z]+)\s+counters?\s+on\s+(?:it|them)$"), COUNTER_PREFIX),
    (re.compile(r"\s+with\s+(?P<kind>defender|flying)$"), ""),
    (re.compile(r"\s+named\s+(?P<name>[^,]+?)$"), NAMED_PREFIX),
)


@dataclass(frozen=True)
class SacrificeItem:
    """One thing the clause sacrifices: the source (``kind == "self"``) or ``count`` objects of ``word``."""

    kind: str
    count: Optional[int] = 1
    word: str = ""


@dataclass(frozen=True)
class SacrificeClause:
    """A parsed "Sacrifice <list>" cost clause and the span of the cost text it covers."""

    items: tuple[SacrificeItem, ...]
    start: int
    end: int

    def span(self) -> tuple[int, int]:
        return self.start, self.end


def _singular(token: str) -> str:
    """A plural noun token → its singular ("elves" → "elf", "lands" → "land", "tokens" → "token")."""
    if token.endswith("ves"):
        return token[:-3] + "f"
    if token.endswith("s"):
        return token[:-1]
    return token


def _is_noun(token: str) -> bool:
    return token in _TYPE_WORDS or token == _TOKEN_WORD or token in SUBTYPES


def _is_known(token: str) -> bool:
    """Whether ``token`` is a word of the shared permanent-phrase vocabulary (`non<type>` negations included)."""
    if token in _ADJECTIVES or _is_noun(token):
        return True
    return token.startswith("non") and token[len("non"):] in _TYPE_WORDS


def _read_phrase(text: str, plural: bool, other: bool) -> Optional[str]:
    """The `matches_permanent_word` encoding of an object phrase, or ``None`` when any word is unknown."""
    tails: list[str] = []
    changed = True
    while changed:
        changed = False
        for pattern, token in _TAIL_PATTERNS:
            match = pattern.search(text)
            if match is None:
                continue
            groups = match.groupdict()
            if token == NAMED_PREFIX:
                tails.append(NAMED_PREFIX + groups["name"].strip())
            elif token == COUNTER_PREFIX:
                tails.append(COUNTER_PREFIX + groups["kind"])
            elif groups.get("kind"):  # "with defender" / "with flying"
                tails.append(groups["kind"])
            elif token:
                tails.append(token)
            text = text[:match.start()]
            changed = True
            break
    runs: list[list[str]] = [[]]
    for token in text.split():
        if token in ("or", "and/or"):
            runs.append([])
        else:
            runs[-1].append(token)
    if not all(runs):
        return None
    for run in runs:
        # Only the last word of a run is the (possibly plural) noun: "eldrazi scions", "blood tokens".
        if plural:
            run[-1] = _singular(run[-1])
        if not all(_is_known(token) for token in run):
            return None
    if not any(_is_noun(token) for token in runs[-1]):
        return None
    # "a black or artifact creature": a run that is only adjectives borrows the final run's noun.
    head_noun = runs[-1][-1]
    for run in runs[:-1]:
        if not any(_is_noun(token) for token in run):
            run.append(head_noun)
    alternatives = ["_".join([*run, *tails]) for run in runs]
    if other:
        alternatives[0] = "other_" + alternatives[0]
    return "_or_".join(alternatives)


def _read_item(text: str) -> Optional[SacrificeItem]:
    text = text.strip()
    if _SELF_RE.match(text):
        return SacrificeItem("self")
    match = _DETERMINER_RE.match(text)
    if match is None:
        return None
    det = match.group("det")
    phrase = match.group("phrase").strip()
    if det in ("a", "an", "another"):
        word = _read_phrase(phrase, plural=False, other=det == "another")
        return SacrificeItem("object", 1, word) if word else None
    count = COUNT_X if det == "x" else int(det) if det.isdigit() else _COUNT_WORDS[det]
    if count is not None and count < 2:
        return None  # "1 creature" has no printed form; a count of one is the singular determiner
    other = phrase.startswith("other ")
    word = _read_phrase(phrase.removeprefix("other "), plural=True, other=other)
    return SacrificeItem("object", count, word) if word else None


def _payable_shape(items: list[SacrificeItem]) -> bool:
    """The item mixes the cost fields can express: the source at most once, and either single objects (each a
    distinct slot) or exactly one counted group -- never both, never two counted groups."""
    counted = [item for item in items if item.kind == "object" and item.count != 1]
    singles = [item for item in items if item.kind == "object" and item.count == 1]
    selves = [item for item in items if item.kind == "self"]
    return len(selves) <= 1 and len(counted) <= 1 and not (counted and singles) and bool(counted or singles)


def read_sacrifice_clause(cost_text: str) -> Optional[SacrificeClause]:
    """The "Sacrifice <list>" clause of ``cost_text`` (lowercase), or ``None`` when it has none or any item of its
    list is outside the grammar (fail closed: the caller then leaves the words unread)."""
    cost_text = cost_text.lower()  # ASCII card text: the lowered string keeps every offset
    verb = _VERB_RE.search(cost_text)
    if verb is None:
        return None
    items: list[SacrificeItem] = []
    position = verb.end()
    end = position
    while True:
        separator = _SEPARATOR_RE.search(cost_text, position)
        stop = separator.start() if separator else len(cost_text)
        item = _read_item(cost_text[position:stop])
        if item is None:
            break
        items.append(item)
        end = stop
        if separator is None:
            break
        position = separator.end()
    if not items or not _payable_shape(items):
        return None
    return SacrificeClause(tuple(items), verb.start(), end)
