"""PAR-144: the "dig" family — "Look at/Reveal the top N cards of your library. You may reveal a
`<kind>` card from among them and put it into your hand. Put the rest on the bottom of your library
in a random order." (Ancient Stirrings, Growing Rites of Itlimoc, Weatherlight, Muxus, Grisly
Salvage, Wrenn and Seven's +1 — ~200 cards sharing one skeleton and varying along four axes).

The four axes, each parsed on its own so a card recombining known values needs no new row:

* **count** — a literal N, or ``x`` (the announced {X} of a spell or activated ability; the sentinel
  means a *different* X under a trigger, which this grammar can't see, so `gate._dig_x_ok` refuses an
  ``x`` count on a triggered ability);
* **what may be taken** — a `models.cards.card_query` criteria dict built from the noun phrase
  (`parse_criteria`: types and subtypes, colours, "nonland", "permanent", "historic", a mana-value
  bound, "{X} in its mana cost"), and *how many* (a / up to N / any number of / all);
* **where it goes** — hand or battlefield;
* **where the rest goes** — bottom of the library, graveyard, or shuffled back in.

The builder emits one ``inspect_top_choose`` (`InspectTopChooseEffect`). Sentences after the dig
are ordinary clauses handed back to the caller's ``match_tail`` (a token, a life gain), except
"if you didn't put a card into your hand this way, <effect>" which becomes the effect's own
``else_effects``. Pure data in, `EffectSpec`s out — no ``game/`` imports (the security boundary).
"""

from __future__ import annotations

import re
from typing import Callable, Optional

from ..spec import EffectSpec
from .subgrammars import resolve_color_word

#: Mana-value comparison words → the `card_query` key they bound.
_MV_BOUND_KEY = {"less": "max_mana_value", "greater": "min_mana_value"}

#: Words naming a card type (or supertype) the criteria builder knows by its type-line spelling.
_TYPE_WORDS = frozenset({
    "artifact", "creature", "enchantment", "instant", "sorcery", "land", "planeswalker", "battle",
    "tribal", "kindred", "legendary", "basic", "snow",
})
#: What "permanent" stands for (RULE 110.1): every type a card can have on the battlefield.
_PERMANENT_TYPES = ["artifact", "creature", "enchantment", "land", "planeswalker", "battle"]
#: RULE 700.6: a historic permanent/spell is an artifact, legendary or a Saga.
_HISTORIC_TYPES = ["artifact", "legendary", "saga"]
#: Adjectives the criteria vocabulary can't express — a phrase using one stays unclaimed rather
#: than being widened to "any card" (fail-closed).
_UNMODELED_WORDS = frozenset({
    "multicolored", "monocolored", "modified", "nontoken", "token", "other", "another", "tapped",
    "untapped", "face-down", "attacking", "blocking", "revealed", "random", "different",
    "differently", "named", "permanent-card", "historic-card", "each", "every", "that", "this",
    "your", "their", "its", "x",
})

_ITEM_SPLIT_RE = re.compile(r",\s*or\s+|\s+or\s+|,\s*")
_ITEM_RE = re.compile(r"(?P<words>[a-z' -]*?)\s*cards?(?P<qual>\s+with .+)?")
_GLOBAL_MV_RE = re.compile(r"(?P<body>.+?) with mana value (?P<n>\d+) or (?P<cmp>less|greater)")
_X_COST_QUAL = "with {x} in its mana cost"
#: A bare "x" (an announced-X magnitude), as opposed to the "{x}" mana symbol of `_X_COST_QUAL`.
_BARE_X_RE = re.compile(r"(?<!\{)\bx\b(?!\})")

#: "put 2 of them into your hand [and the rest …]" — a pick with no kind restriction.
_PICK_OF_THEM_RE = re.compile(
    r"put (?P<up_to>up to )?(?P<n>\d+) of them into your hand(?: and the rest (?P<rest>.+))?"
)
#: The selection sentence. ``verb`` "reveal" is only valid with its "and put it" half.
_SELECTION_RE = re.compile(
    r"(?P<may>you may )?(?P<verb>reveal|put) "
    r"(?P<quant>an?|one|up to \d+|any number of|all) (?P<crit>.+?) "
    r"(?P<where>from among (?:them|the revealed cards)|revealed this way)"
    r"(?P<andput> and put (?:it|that card|them|those cards|the revealed cards))?"
    r" (?P<dest>into your hand|onto the battlefield(?: tapped(?: and attacking)?)?)"
    r"(?: and the rest (?P<rest>.+))?"
)
#: "the rest …" as the tail of the selection sentence, or its own following sentence.
_REST_DEST_RE = re.compile(
    r"(?P<bottom>on the bottom of your library in (?:a random|any) order)|"
    r"(?P<graveyard>into your graveyard)"
)
_REST_SENTENCE_RE = re.compile(
    r"(?:then )?put (?:the rest(?: of (?:the cards revealed this way|them))?|"
    r"all (?:the )?cards revealed this way that weren't put (?:onto the battlefield|into your hand)) "
    r"(?P<dest>.+)"
)
_SHUFFLE_REST_RE = re.compile(r"(?:then )?shuffle the rest into your library")
_ELSE_TAIL_RE = re.compile(r"if you didn't put a card into your hand this way, (?P<effect>.+)")
_SENTENCE_SPLIT_RE = re.compile(r"\.\s+")

_ACTION_BY_DEST = {
    "into your hand": "library_to_hand",
    "onto the battlefield": "library_to_battlefield",
    "onto the battlefield tapped": "library_to_battlefield_tapped",
    # PAR-148 (RULE 508.4)
    "onto the battlefield tapped and attacking": "library_to_battlefield_attacking",
}


def _item_criteria(words: str, qual: str, global_mv: Optional[tuple[str, int]]) -> Optional[dict]:
    """One noun-phrase item ("legendary artifact", "tyvar", "") → a `card_query` dict."""
    criteria: dict = {}
    plain: list[str] = []
    type_or: Optional[list[str]] = None
    colors: list[str] = []
    without: list[str] = []
    for word in words.split():
        if word in _UNMODELED_WORDS:
            return None
        color = resolve_color_word(word) if word != "colorless" else "colorless"
        if color:
            colors.append(color)
        elif word == "permanent":
            type_or = list(_PERMANENT_TYPES)
        elif word == "historic":
            type_or = list(_HISTORIC_TYPES)
        elif word == "nonlegendary":
            criteria["nonlegendary"] = True
        elif word.startswith("non") and word[3:] in _TYPE_WORDS:
            without.append(word[3:])
        elif re.fullmatch(r"[a-z]+", word):
            plain.append(word)
        else:
            return None
    if type_or is not None and plain:
        return None  # "permanent" with another type word: an AND of an OR-list `card_query` can't hold
    if type_or is not None:
        criteria["type"] = [t for t in type_or if t not in without]
        without = []
    elif len(plain) == 1:
        criteria["type"] = plain[0]
    elif plain:
        criteria["all_types"] = plain
    if without:
        criteria["without_type"] = without
    if colors:
        criteria["color"] = colors
    qual = qual.strip()
    if qual:
        if qual != _X_COST_QUAL:
            return None
        criteria["has_x_cost"] = True
    if global_mv is not None:
        criteria[global_mv[0]] = global_mv[1]
    return criteria


def parse_criteria(phrase: str) -> Optional[dict]:
    """A dig noun phrase ("an elf, warrior, or tyvar card", "a land card or a card with {x} in its
    mana cost", "creature cards with mana value 3 or less") → a `card_query` dict, ``None`` when
    any part is outside the vocabulary. A bare "card"/"cards" is ``{}`` (any card)."""
    phrase = phrase.strip()
    if "and/or" in phrase or " and " in phrase or _BARE_X_RE.search(phrase):
        return None
    global_mv: Optional[tuple[str, int]] = None
    mv = _GLOBAL_MV_RE.fullmatch(phrase)
    if mv is not None:
        phrase = mv.group("body")
        global_mv = (_MV_BOUND_KEY[mv.group("cmp")], int(mv.group("n")))
    items: list[dict] = []
    raw_items = [re.sub(r"^(?:an?|the)\s+", "", i.strip()) for i in _ITEM_SPLIT_RE.split(phrase) if i.strip()]
    if not raw_items:
        return None
    # An item written without the word "card" ("elf", "warrior" in "an elf, warrior, or tyvar card")
    # is one of the bare type words ahead of the item that does carry it.
    for index, item in enumerate(raw_items):
        item_match = _ITEM_RE.fullmatch(item)
        if item_match is not None:
            words, qual = item_match.group("words"), item_match.group("qual") or ""
        elif index < len(raw_items) - 1 and re.fullmatch(r"[a-z' -]+", item):
            words, qual = item, ""
        else:
            return None
        built = _item_criteria(words, qual, None)
        if built is None:
            return None
        items.append(built)
    if len(items) == 1:
        merged = items[0]
    elif all(set(i) == {"type"} for i in items):
        types: list[str] = []
        for item in items:
            value = item["type"]
            types.extend(value if isinstance(value, list) else [value])
        merged = {"type": types}
    else:
        merged = {"or": items}
    if global_mv is not None:
        merged = {**merged, global_mv[0]: global_mv[1]}
    return merged


def _rest_destination(text: str) -> Optional[str]:
    match = _REST_DEST_RE.fullmatch(text.strip())
    if match is None:
        return None
    return "library_bottom_random" if match.group("bottom") else "graveyard"


def parse_dig(
    count: "int | str", remainder: str, match_tail: Callable[[str], Optional[list[EffectSpec]]],
) -> Optional[list[EffectSpec]]:
    """The `EffectSpec`s for a dig whose first sentence ("look at/reveal the top N cards of your
    library") was already read: ``remainder`` is every sentence after it."""
    sentences = [s.strip().rstrip(".") for s in _SENTENCE_SPLIT_RE.split(remainder) if s.strip()]
    if not sentences:
        return None
    selection, tails = sentences[0], sentences[1:]
    params: dict = {"count": count}

    pick = _PICK_OF_THEM_RE.fullmatch(selection)
    rest_text: Optional[str]
    if pick is not None:
        params.update(
            action="library_to_hand", max_picks=int(pick.group("n")), optional=bool(pick.group("up_to")),
        )
        rest_text = pick.group("rest")
    else:
        sel = _SELECTION_RE.fullmatch(selection)
        if sel is None or (sel.group("verb") == "reveal") != bool(sel.group("andput")):
            return None
        criteria = parse_criteria(sel.group("crit"))
        if criteria is None:
            return None
        quant = sel.group("quant")
        everything = quant in ("all", "any number of")
        optional = bool(sel.group("may")) or quant.startswith("up to") or quant == "any number of"
        if quant == "all" and sel.group("may"):
            return None
        params.update(
            action=_ACTION_BY_DEST[sel.group("dest")],
            max_picks="all" if everything else (int(quant.split()[-1]) if quant.startswith("up to") else 1),
            optional=optional,
        )
        if criteria:
            params["criteria"] = criteria
        rest_text = sel.group("rest")

    if rest_text is not None:
        rest_dest = _rest_destination(rest_text)
    elif tails and _SHUFFLE_REST_RE.fullmatch(tails[0]):
        rest_dest, tails = "library_shuffled", tails[1:]
    elif tails and (rest_sentence := _REST_SENTENCE_RE.fullmatch(tails[0])) is not None:
        rest_dest, tails = _rest_destination(rest_sentence.group("dest")), tails[1:]
    else:
        rest_dest = None
    if rest_dest is None:
        return None
    params["rest_destination"] = rest_dest

    specs: list[EffectSpec] = []
    for tail in tails:
        else_tail = _ELSE_TAIL_RE.fullmatch(tail)
        if else_tail is not None and "else_effects" not in params:
            effects = match_tail(else_tail.group("effect"))
            if effects is None:
                return None
            params["else_effects"] = [spec.to_dict() for spec in effects]
            continue
        effects = match_tail(tail)
        if effects is None:
            return None
        specs.extend(effects)
    return [EffectSpec("inspect_top_choose", params), *specs]
