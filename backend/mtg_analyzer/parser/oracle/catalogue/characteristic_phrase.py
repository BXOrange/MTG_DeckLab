"""Characteristic phrases → `combat.matches_object_filter` dicts (PAR-119/120).

One composable grammar for "what kind of object" — the adjectives, card types,
subtypes, colours and `with <qualifier>` tails that every trigger head, target
phrase and count phrase re-spelled on its own::

    phrase  := head [" with " qualifier]
    head    := WORD+                       "legendary creature", "goblin warrior"
             | WORD (("," | " or ") WORD)+ "instant or sorcery", "goblin or wizard"
    qualifier := "mana value N or greater|less"
               | "power|toughness N or greater|less"
               | "a [<kind>] counter on it"
               | "<keyword>"

A phrase either parses completely into a filter dict or returns ``None``
(fail-closed) — an unknown word is never guessed at (`static_handlers.
object_filter`'s subtype fallback turns "multicolored" into a *subtype*, which
is why this grammar carries its own closed vocabulary instead). Adding a word to
a table below is the whole cost of a new adjective; a card recombining known
words needs no code at all. Subtypes come from `subtype_vocabulary` (generated
from the card cache). Pure — no `game/` imports (parser security boundary).
"""

from __future__ import annotations

import re
from typing import Any, Optional

from .subtype_vocabulary import SUBTYPES
from .trigger_context import CONTROLLER_TAILS

#: Main card types a phrase may name (RULE 300.1).
CARD_TYPES: frozenset[str] = frozenset(
    {"creature", "artifact", "enchantment", "instant", "sorcery", "planeswalker", "land", "battle"}
)

#: "permanent" names no restriction of its own (RULE 110.1): every object on the
#: battlefield is one. Accepted as a noun so "a permanent you control" parses.
#: "source" (RULE 609.7) is likewise any object — a permanent, or a spell that is
#: dealing damage — so "a source you control" restricts only by controller.
NOUN_ONLY_WORDS: frozenset[str] = frozenset({"permanent", "source"})

#: The card types a permanent can have — what "a permanent **card**" means for a
#: card that is not on the battlefield (a discarded one), RULE 110.1.
PERMANENT_CARD_TYPES: tuple[str, ...] = (
    "creature", "artifact", "enchantment", "land", "planeswalker", "battle",
)

#: Colour word → `matches_object_filter`'s colour letter (RULE 105.1).
COLOR_LETTERS: dict[str, str] = {
    "white": "W", "blue": "U", "black": "B", "red": "R", "green": "G",
}

#: Boolean adjectives → the filter key they set. Each key exists on
#: `combat.matches_object_filter` (the new ones were added with this module).
FLAG_WORDS: dict[str, dict[str, Any]] = {
    "multicolored": {"multicolored": True},
    "colorless": {"colorless": True},
    "legendary": {"legendary": True},
    "nonlegendary": {"nonlegendary": True},
    "kicked": {"kicked": True},
    "token": {"token": True},
    "nontoken": {"nontoken": True},
    "tapped": {"tapped": True},
    "untapped": {"tapped": False},
    "basic": {"basic": True},
    "nonbasic": {"nonbasic": True},
    "snow": {"snow": True},
    "attacking": {"attacking": True},
    "blocking": {"blocking": True},
    # RULE 903.3: a commander is a designation, not a type or subtype.
    "commander": {"is_commander": True},
    # RULE 205.3m's collective terms: one word standing for several creature types
    # ("outlaw" = Assassin, Mercenary, Pirate, Rogue or Warlock), and RULE 700.6's
    # "historic" (an artifact, a legendary permanent or a Saga).
    "outlaw": {"subtype_any": ["assassin", "mercenary", "pirate", "rogue", "warlock"]},
    "historic": {"any_of": [{"card_type": "artifact"}, {"legendary": True}, {"subtype": "saga"}]},
}

#: Keywords a "with <keyword>" tail may name, → the printed keyword string
#: `combat.has` compares against. Deliberately the ones cards actually print in
#: trigger text; extend when a real card needs one.
KEYWORD_WORDS: dict[str, str] = {
    "flying": "flying", "haste": "haste", "reach": "reach", "menace": "menace",
    "defender": "defender", "shadow": "shadow", "first strike": "first strike",
    "cascade": "cascade", "flash": "flash", "convoke": "convoke", "delve": "delve",
    "deathtouch": "deathtouch", "lifelink": "lifelink", "trample": "trample",
    "vigilance": "vigilance", "double strike": "double strike", "infect": "infect",
    "persist": "persist", "undying": "undying", "changeling": "changeling",
}

_ALTERNATION = re.compile(r"\s*,\s*(?:(?:and/)?or\s+|and\s+)?|\s+(?:(?:and/)?or|and)\s+")
#: What makes a word list an OR rather than stacked adjectives: an explicit
#: "or"/"and/or" connective, or — for a *plural* count noun only — "and"
#: ("instant and sorcery cards", "Soldiers and Warriors you control" name every
#: card that is either). A comma list with no connective at all ("noncreature,
#: nonland card") is stacked adjectives, i.e. AND.
_OR_CONNECTIVE = re.compile(r"\s(?:and/)?or\s")
_PLURAL_AND_CONNECTIVE = re.compile(r"\sand\s")
_WITH_MANA_VALUE = re.compile(r"^mana value (?P<n>\d+) or (?P<dir>greater|less)$")
_WITH_STAT = re.compile(r"^(?P<stat>power|toughness) (?P<n>\d+) or (?P<dir>greater|less)$")
_WITH_COUNTER = re.compile(r"^an? (?:(?P<kind>\+1/\+1|-1/-1|[a-z]+) )?counter on it$")
_NON_SUBTYPE = re.compile(r"^non-?(?P<sub>[a-z]+)$")


def _bound(key_stem: str, n: int, direction: str) -> dict[str, Any]:
    """"N or greater" → ``min_<stem>``; "N or less" → ``max_<stem>``."""
    return {("min_" if direction == "greater" else "max_") + key_stem: n}


def _singulars(word: str) -> list[str]:
    """The singular forms a plural noun could be ("elves" → elf, "wolves" → wolf,
    "lands" → land), most specific first."""
    out: list[str] = []
    if word.endswith("i"):
        out.append(word[:-1] + "us")  # "fungi" → fungus
    if word.endswith("ies"):
        out.append(word[:-3] + "y")
    if word.endswith("ves"):
        out += [word[:-3] + "f", word[:-3] + "fe"]
    if word.endswith("es"):
        out.append(word[:-2])
    if word.endswith("s"):
        out.append(word[:-1])
    return out


def _word_fragment(word: str, plural: bool = False) -> Optional[dict[str, Any]]:
    """One head word → its filter fragment (``{}`` for a bare noun), or ``None``."""
    if word in NOUN_ONLY_WORDS:
        return {}
    if word in CARD_TYPES:
        return {"card_type": word}
    if word in COLOR_LETTERS:
        return {"color": COLOR_LETTERS[word]}
    if word in FLAG_WORDS:
        return dict(FLAG_WORDS[word])
    if word.startswith("non"):
        stem = _NON_SUBTYPE.match(word)
        if stem is not None:
            if stem.group("sub") in CARD_TYPES:
                return {"without_card_type": stem.group("sub")}
            if stem.group("sub") in COLOR_LETTERS:
                return {"without_color": COLOR_LETTERS[stem.group("sub")]}
            if stem.group("sub") in SUBTYPES:
                return {"without_subtype": stem.group("sub")}
    if plural:
        # A plural noun names its singular type ("elves" → Elf, even though one odd
        # card prints an "Elves" subtype of its own).
        for singular in _singulars(word):
            fragment = _word_fragment(singular)
            if fragment is not None:
                return fragment
    if word in SUBTYPES:
        return {"subtype": word}
    return None


def _conjunction(
    words: list[str], card_noun: bool = False, plural: bool = False
) -> Optional[dict[str, Any]]:
    """Adjacent head words → one AND-ed filter. With ``card_noun`` the phrase is
    about cards outside the battlefield ("a permanent card"), where "permanent"
    is a restriction (not an instant or sorcery) rather than an empty noun."""
    filt: dict[str, Any] = {}
    card_types: list[str] = []
    for index, word in enumerate(words):
        is_noun = index == len(words) - 1  # only the head noun may be plural
        if card_noun and word in ("permanent", "permanents"):
            fragment: Optional[dict[str, Any]] = {"card_type_any": list(PERMANENT_CARD_TYPES)}
        else:
            fragment = _word_fragment(word, plural=plural and is_noun)
        if fragment is None:
            return None
        if fragment.get("card_type"):
            card_types.append(fragment["card_type"])
            continue
        if "without_card_type" in fragment and "without_card_type" in filt:
            # "noncreature, nonland" — stacked exclusions, every one applies.
            previous = filt["without_card_type"]
            previous = previous if isinstance(previous, list) else [previous]
            if fragment["without_card_type"] in previous:
                return None
            filt["without_card_type"] = previous + [fragment["without_card_type"]]
            continue
        if any(k in filt for k in fragment):
            return None  # two subtypes / two colours / a repeated word: not one object's phrase
        filt.update(fragment)
    if len(card_types) == 1:
        filt["card_type"] = card_types[0]
    elif card_types:
        # "artifact creature" — every named type at once.
        if len(set(card_types)) != len(card_types):
            return None
        filt["card_type_all"] = card_types
    return filt


def _alternation(parts: list[str], plural: bool = False) -> Optional[dict[str, Any]]:
    """The OR of several single-word parts: "instant or sorcery", "goblin or wizard"."""
    if any(len(p.split()) != 1 for p in parts):
        # Whether a leading adjective distributes over every alternative
        # ("nontoken artifact creature or vehicle") is not decidable from the
        # words — refuse rather than guess.
        return None
    fragments = [_word_fragment(p, plural=plural) for p in parts]
    if any(f is None or not f for f in fragments):
        return None
    if all(set(f) == {"card_type"} for f in fragments):
        return {"card_type_any": [f["card_type"] for f in fragments]}
    if all(set(f) == {"color"} for f in fragments):
        return {"color_any": [f["color"] for f in fragments]}
    if all(set(f) == {"subtype"} for f in fragments):
        return {"subtype_any": [f["subtype"] for f in fragments]}
    if all(all(k.startswith("without_") for k in f) for f in fragments):
        merged: dict[str, Any] = {}
        for f in fragments:
            for k, v in f.items():
                if k in merged:
                    prev = merged[k]
                    prev = prev if isinstance(prev, list) else [prev]
                    merged[k] = prev + [v]
                else:
                    merged[k] = v
        return merged
    return {"any_of": fragments}


def parse_head(head: str, plural: bool = False) -> Optional[dict[str, Any]]:
    """The adjective/type words before a noun — "" is the unfiltered phrase.

    A trailing "card"/"cards" noun ("a land card", "a nonland card") is not part
    of the filter; it only marks the phrase as being about cards in a zone other
    than the battlefield."""
    head = head.strip().lower()
    card_noun = False
    for noun in (" cards", " card"):  # ("cards" is only a noun here, never an adjective)
        if head.endswith(noun):
            head, card_noun = head[: -len(noun)].strip(), True
            break
    if head in ("card", "cards"):
        head, card_noun = "", True
    if not head:
        return {}
    if _OR_CONNECTIVE.search(head) or (plural and _PLURAL_AND_CONNECTIVE.search(head)):
        parts = [p for p in _ALTERNATION.split(head) if p]
        return _alternation(parts, plural=plural)
    return _conjunction(head.replace(",", " ").split(), card_noun=card_noun, plural=plural)


def parse_qualifier(qualifier: str) -> Optional[dict[str, Any]]:
    """The text after "with " → filter keys, or ``None``."""
    qualifier = qualifier.strip().lower()
    m = _WITH_MANA_VALUE.match(qualifier)
    if m:
        return _bound("mana_value", int(m.group("n")), m.group("dir"))
    m = _WITH_STAT.match(qualifier)
    if m:
        return _bound(m.group("stat"), int(m.group("n")), m.group("dir"))
    m = _WITH_COUNTER.match(qualifier)
    if m:
        # The kindless "a counter on it" is any counter (RULE 122.1).
        return {"has_counter_kind": m.group("kind")} if m.group("kind") else {"has_counter": True}
    if qualifier in KEYWORD_WORDS:
        return {"keyword": KEYWORD_WORDS[qualifier]}
    return None


def parse_characteristic_phrase(text: str) -> Optional[dict[str, Any]]:
    """``head [with qualifier]`` → one merged filter dict, or ``None`` if any part is unknown."""
    head, sep, qualifier = text.strip().lower().partition(" with ")
    filt = parse_head(head)
    if filt is None:
        return None
    if sep:
        extra = parse_qualifier(qualifier)
        if extra is None or any(k in filt for k in extra):
            return None
        filt.update(extra)
    return filt


#: Where a noun phrase's head ends and its tails begin: a controller phrase, a
#: "with <qualifier>", or an "of the chosen <color|type>".
_TAIL_MARKER = re.compile(
    r"\s(?=(?:" + "|".join(re.escape(t) for t, _ in CONTROLLER_TAILS) + r"|with|of the chosen)\b)"
)
_TAIL_QUALIFIER = re.compile(
    r"^with (?P<q>.+?)(?=\s+(?:" + "|".join(re.escape(t) for t, _ in CONTROLLER_TAILS)
    + r"|of the chosen)\b|$)"
)
_CHOSEN_TAILS = {
    "of the chosen color": {"color_from_source": True},
    "of the chosen type": {"subtype_from_source": True},
}


def parse_object_phrase(
    text: str, plural: bool = False
) -> Optional[tuple[dict[str, Any], Optional[str]]]:
    """A noun phrase with its tails → ``(filter, controller)``, or ``None``.

    ``"nontoken creature you control with power 4 or greater"`` →
    ``({"nontoken": True, "card_type": "creature", "min_power": 4}, "you")``.
    ``controller`` is ``"you"``/``"not_you"``, or ``None`` when the phrase names
    none. Tails may come in either order ("with flying you control" and "you
    control with flying" both occur); a repeated tail, or any unknown word,
    fails the whole phrase.
    """
    text = text.strip().lower()
    marker = _TAIL_MARKER.search(text)
    head, rest = (text[: marker.start()], text[marker.start():].strip()) if marker else (text, "")
    filt = parse_head(head, plural=plural)
    if filt is None:
        return None
    controller: Optional[str] = None
    while rest:
        matched = False
        for phrase, scope in CONTROLLER_TAILS:
            if rest.startswith(phrase):
                if controller is not None:
                    return None
                controller, rest, matched = scope, rest[len(phrase):].strip(), True
                break
        if matched:
            continue
        for phrase, keys in _CHOSEN_TAILS.items():
            if rest.startswith(phrase):
                if any(k in filt for k in keys):
                    return None
                filt.update(keys)
                rest, matched = rest[len(phrase):].strip(), True
                break
        if matched:
            continue
        q = _TAIL_QUALIFIER.match(rest)
        if q is None:
            return None
        extra = parse_qualifier(q.group("q"))
        if extra is None or any(k in filt for k in extra):
            return None
        filt.update(extra)
        rest = rest[q.end():].strip()
    return filt, controller
