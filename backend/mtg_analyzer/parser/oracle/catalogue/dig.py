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
* **where it goes** — hand, battlefield, graveyard or back on top;
* **where the rest goes** — bottom of the library, graveyard, exile, or shuffled back in.

The builder emits one ``inspect_top_choose`` (`InspectTopChooseEffect`). Sentences after the dig
are ordinary clauses handed back to the caller's ``match_tail`` (a token, a life gain), except
"if you didn't put a card into your hand this way, <effect>" which becomes the effect's own
``else_effects``. Pure data in, `EffectSpec`s out — no ``game/`` imports (the security boundary).
"""

from __future__ import annotations

import re
from typing import Callable, Optional

from ..spec import EffectSpec
from .casting_window import CARD_TYPE_CRITERIA, CARD_TYPE_WORD, parse_pick_cast_window
from .count_phrase import parse_amount_phrase
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

#: (an "or less" / "or greater" is a bound's tail, not an alternative: `_BOUND_QUAL_RE`)
_ITEM_SPLIT_RE = re.compile(r",\s*or\s+|\s+or\s+(?!less\b|greater\b)|,\s*")
_ITEM_RE = re.compile(r"(?P<words>[a-z' -]*?)\s*cards?(?P<qual>\s+(?:with|of the chosen type|that shares).*)?")
_GLOBAL_MV_RE = re.compile(r"(?P<body>.+?) with mana value (?P<n>\d+|x) or (?P<cmp>less|greater)")
#: PAR-292 M19: the bound's "X" is the dig's own count X (the announced {X} or the `bind` of a "where X is ..." clause,
#: both of which rewrite the ``"x"`` marker). `_MV_X_MARKER` is that marker in the `card_query` dict; `parse_dig` only
#: lets it through when the dig's count is that same X, and `gate._dig_x_ok` refuses it under a trigger.
MV_X_MARKER = "x"
#: A bare "x" that is a mana-value bound's operand ("mana value x or less"), the one spelling `parse_criteria` admits.
_MV_X_BOUND_RE = re.compile(r"(?<=mana value )x(?= or (?:less|greater)\b)")
_X_COST_QUAL = "with {x} in its mana cost"
_CHOSEN_TYPE_QUAL = "of the chosen type"
#: The placeholder `InspectTopChooseEffect._resolved_criteria` swaps for the source's chosen creature type.
CHOSEN_TYPE_TOKEN = "chosen_type"
#: The `card_query` ``shares_creature_type_with`` placeholders (kept equal to `game.effects.returns_graveyards`', which
#: the parser may not import).
SHARED_TYPE_SOURCE = "source"
SHARED_TYPE_TRIGGER_CREATURE = "trigger_creature"
#: PAR-292 M11: a per-item numeric bound ("a creature card with power 2 or less", "an artifact card with
#: mana value 3 or less") -> the `card_query` key it sets (`max_power`, `min_toughness`, `max_mana_value`, ...).
_BOUND_QUAL_RE = re.compile(r"with (?P<stat>power|toughness|mana value) (?P<n>\d+|x) or (?P<cmp>less|greater)")
#: PAR-292 M12: "a card that shares a creature type with it / ~ / that creature" -> the `card_query`
#: ``shares_creature_type_with`` placeholder the effect resolves to the reference's creature types (RULE 205.3m).
_SHARES_TYPE_QUAL_RE = re.compile(r"that shares a creature type with (?P<ref>it|~|that creature)")
_SHARES_TYPE_REFERENCE = {
    "it": SHARED_TYPE_SOURCE, "~": SHARED_TYPE_SOURCE, "that creature": SHARED_TYPE_TRIGGER_CREATURE,
}
_BOUND_STAT_KEY = {"power": "power", "toughness": "toughness", "mana value": "mana_value"}
_BOUND_CMP_PREFIX = {"less": "max_", "greater": "min_"}
#: "a creature card and/or a land card": separate "a" items joined by and/or (one card per type word).
_SEPARATE_ITEMS_RE = re.compile(r"(?P<a>[a-z]+) card and/or an? (?P<b>[a-z]+) card")
#: PAR-292 M29: the same one-card-per-slot list with any number of slots and subtype / qualified items ("a Cleric card, a
#: Rogue card, a Warrior card, and/or a Wizard card"; the leading "a" is the selection's `quant`). Items are separated by
#: a comma and/or an "and/or" / "and", each introduced by its own article.
SLOT_SPLIT_RE = re.compile(r"(?:,\s*(?:and/or\s+|and\s+)?|\s+and/or\s+|\s+and\s+)an?\s+")
#: The most slots a "one card per slot" pick names (Harper Recruiter prints four); more is not a known printing.
MAX_PICK_SLOTS = 4


def parse_pick_slots(crit: str) -> Optional[list[dict]]:
    """The slots of "a <A> card[,] [and/or] a <B> card ..." (``crit`` is what follows the first article), one
    `card_query` dict per slot, ``None`` when it is not a slot list (a single kind, a union, an unreadable item). Each
    slot may be filled by at most one card, each card fills at most one slot (RULE 608.2c)."""
    items = SLOT_SPLIT_RE.split(crit.strip())
    if not 2 <= len(items) <= MAX_PICK_SLOTS or not all(item.endswith(" card") for item in items):
        return None
    slots = [parse_criteria(item) for item in items]
    if any(not slot for slot in slots):
        return None
    return slots
#: RULE 205.2a: the card types a "distinct types" pick can tell apart (the same set the engine's
#: `distinct_card_types` assignment reads, `misc_helpers.CARD_TYPE_WORDS`).
_DISTINCT_TYPE_WORDS = frozenset({"artifact", "creature", "enchantment", "instant", "land", "planeswalker", "sorcery", "battle"})
#: PAR-292 M18: "that many cards" -- the count operand of a dig whose quantity is the firing event's payload. The
#: ``field`` is a private sentinel the gate swaps for the real payload field of the enclosing trigger (RULE 608.2h), or
#: refuses when no trigger names the quantity.
THAT_MANY_FIELD = "that_much"
THAT_MANY_COUNT = {"kind": "trigger_event", "field": THAT_MANY_FIELD}
#: A bare "x" (an announced-X magnitude), as opposed to the "{x}" mana symbol of `_X_COST_QUAL`.
_BARE_X_RE = re.compile(r"(?<!\{)\bx\b(?!\})")

#: A numbered pick with no kind restriction, optionally returned to the top.
_PICK_OF_THEM_RE = re.compile(
    r"(?P<may>you may )?put (?P<up_to>up to )?(?P<n>\d+) of (?:them|those cards) "
    r"(?P<dest>into your hand|into your graveyard|(?:back )?on top of your library)"
    # RULE 406.3: "... put one of them into your hand, and exile the rest" (Browse) = the pick plus an exiled rest.
    r"(?:,? and (?:(?P<rest_group>the rest|the other) (?P<rest>.+)|(?P<exile_rest>exile the rest)))?"
)
#: The selection sentence. ``verb`` "reveal" is only valid with its "and put it" half.
_SELECTION_RE = re.compile(
    r"(?P<may>you may )?(?P<verb>reveal|put) "
    r"(?P<quant>an?|one|up to \d+|any number of|all) (?P<crit>.+?) "
    r"(?P<where>from among (?:them|the revealed cards)|revealed this way)"
    r"(?P<andput> and put (?:it|that card|them|those cards|the revealed cards))?"
    r" (?P<dest>into your hand|on top of your library|onto the battlefield(?: tapped(?: and attacking)?)?)"
    r"(?:, (?P<shuffle>then shuffle)| and the rest (?P<rest>.+))?"
)
#: PAR-292 M12: the exile pick, which has no destination word of its own ("you may exile a creature card from among them",
#: "exile 1 of them face down", "exile 1 face down and put the rest ...") and is followed by a casting window.
_EXILE_PICK_RE = re.compile(
    r"(?P<may>you may )?exile (?:(?P<quant>an?|1) (?P<crit>.+?) from among (?:them|those cards)"
    r"|(?P<one>1)(?: of (?:them|those cards))?)(?P<down> face down)?"
    r"(?: and put (?P<rest_group>the rest|the other) (?P<rest>.+))?"
)
#: "the rest …" as the tail of the selection sentence, or its own following sentence.
_REST_DEST_RE = re.compile(
    r"(?P<bottom>on the bottom(?: of your library)? in (?:a random|any) order)|"  # "of your library" is implied (There's Coffee in that Nebula)
    r"(?P<graveyard>into your graveyard)"
)
_REST_SENTENCE_RE = re.compile(
    r"(?:then )?put (?:(?P<other>the other)|the rest(?: of (?:the cards revealed this way|them))?|"
    r"all (?:the )?cards revealed this way that weren't put (?:onto the battlefield|into your hand)) "
    r"(?P<dest>.+)"
)
_SHUFFLE_REST_RE = re.compile(r"(?:then )?shuffle(?: the rest into your library)?")
_ELSE_TAIL_RE = re.compile(r"if you didn't put a card into your hand this way, (?P<effect>.+)")
_SENTENCE_SPLIT_RE = re.compile(r"\.\s+")

#: The `InspectTopChooseEffect` action that reveals just the picked card as it moves library -> hand (kept equal to
#: `chosen_object_actions_mixin`'s spelling, which the parser may not import).
REVEAL_PICK_TO_HAND_ACTION = "reveal_library_to_hand"

_ACTION_BY_DEST = {
    "into your hand": "library_to_hand",
    "into your graveyard": "library_to_graveyard",
    "on top of your library": "library_top",
    "back on top of your library": "library_top",
    "onto the battlefield": "library_to_battlefield",
    "onto the battlefield tapped": "library_to_battlefield_tapped",
    # PAR-148 (RULE 508.4)
    "onto the battlefield tapped and attacking": "library_to_battlefield_attacking",
}


def _item_criteria(words: str, qual: str, global_mv: Optional[tuple[str, "int | str"]]) -> Optional[dict]:
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
        bound = _BOUND_QUAL_RE.fullmatch(qual)
        if bound is not None:
            if bound.group("n") == MV_X_MARKER and bound.group("stat") != "mana value":
                return None  # only a mana-value bound can be the dig's X
            criteria[_BOUND_CMP_PREFIX[bound.group("cmp")] + _BOUND_STAT_KEY[bound.group("stat")]] = (
                MV_X_MARKER if bound.group("n") == MV_X_MARKER else int(bound.group("n")))
        elif qual == _CHOSEN_TYPE_QUAL and len(plain) == 1:
            # "a creature card of the chosen type" (Icon of Ancestry): the type picked as the source entered, read by
            # `InspectTopChooseEffect._resolved_criteria` when the dig resolves.
            criteria.pop("type", None)
            criteria["all_types"] = [plain[0], CHOSEN_TYPE_TOKEN]
        elif (shares := _SHARES_TYPE_QUAL_RE.fullmatch(qual)) is not None:
            criteria["shares_creature_type_with"] = _SHARES_TYPE_REFERENCE[shares.group("ref")]
        elif qual == _X_COST_QUAL:
            criteria["has_x_cost"] = True
        else:
            return None
    if global_mv is not None:
        criteria[global_mv[0]] = global_mv[1]
    return criteria


def parse_criteria(phrase: str, union_and: bool = False) -> Optional[dict]:
    """A dig noun phrase ("an elf, warrior, or tyvar card", "a land card or a card with {x} in its
    mana cost", "creature cards with mana value 3 or less") → a `card_query` dict, ``None`` when
    any part is outside the vocabulary. A bare "card"/"cards" is ``{}`` (any card).

    ``union_and``: the caller knows the quantity is plural ("any number of", "up to N", "all"), where "creature and/or
    land cards" / "creature and land cards" name the union of both kinds; for a single pick it stays refused."""
    phrase = phrase.strip()
    if union_and:
        phrase = re.sub(r"\s+and/or\s+|\s+and\s+", " or ", phrase)
    if "and/or" in phrase or " and " in phrase or _BARE_X_RE.search(_MV_X_BOUND_RE.sub("", phrase)):
        return None
    global_mv: Optional[tuple[str, "int | str"]] = None
    mv = _GLOBAL_MV_RE.fullmatch(phrase)
    if mv is not None:
        phrase = mv.group("body")
        global_mv = (_MV_BOUND_KEY[mv.group("cmp")], MV_X_MARKER if mv.group("n") == MV_X_MARKER else int(mv.group("n")))
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
    if match.group("bottom"):
        # RULE 401.4: "in any order" is the player's own choice of the pile's order, "in a random order" is not.
        return "library_bottom_random" if "random" in match.group("bottom") else "library_bottom_order"
    return "graveyard"


#: PAR-148: "Reveal the top card of your library. If it's a `<kind>` card, put it onto the battlefield [tapped [and
#: attacking]]. Otherwise, put it into your hand/graveyard." (Call of the Wild, Skyward Eye Prophets, Hans Eriksson) and
#: "…you may reveal the top card … if a `<kind>` card is revealed this way, put it …" (Doors of Durin): a one-card dig
#: whose hit is forced. No "otherwise" leaves the card on top (``decline_leaves_untouched``).
_REVEAL_TOP_BRANCH_RE = re.compile(
    r"(?P<may>you may )?reveal the top card of your library\.\s+"
    r"if (?:(?:it'?s|that card is) an? (?P<crit>[a-z' -]+?) card|an? (?P<crit2>[a-z' -]+?) card is revealed this way), "
    r"put it (?P<dest>onto the battlefield(?: tapped(?: and attacking)?)?|into your hand)"
    r"(?:\.\s+otherwise, put (?:it|that card) (?P<rest>into your hand|into your graveyard))?\.?"
)
_REVEAL_REST = {"into your hand": "hand", "into your graveyard": "graveyard"}


def parse_reveal_top_branch(text: str) -> Optional[list[EffectSpec]]:
    """The `inspect_top_choose` spec for a one-card reveal-and-branch clause, else ``None``."""
    m = _REVEAL_TOP_BRANCH_RE.fullmatch(text.strip())
    if m is None:
        return None
    criteria = parse_criteria(f'{m.group("crit") or m.group("crit2")} card')
    if not criteria:
        return None  # an unreadable (or empty) kind would turn "if it's a creature" into "always"
    params: dict = {
        "count": 1, "action": _ACTION_BY_DEST[m.group("dest")], "max_picks": 1,
        "optional": bool(m.group("may")), "criteria": criteria,
        "reveal": True,  # RULE 701.20a: the clause opens with "reveal the top card"
    }
    if m.group("rest"):
        params["rest_destination"] = _REVEAL_REST[m.group("rest")]
    else:
        params["rest_destination"] = "library_top"
        params["decline_leaves_untouched"] = True
    return [EffectSpec("inspect_top_choose", params)]


#: PAR-292 M19: the free-cast pick, "you may cast a [<type>] spell [with mana value <cap>] from among them without paying
#: its mana cost" (RULE 608.2g, 118.9): the dig's action is a cast during this resolution, not a move.
_CAST_PICK_RE = re.compile(
    rf"you may cast an? (?:(?P<type>{CARD_TYPE_WORD}) )?spell(?: with mana value (?P<cap>.+?))?"
    r" from among them(?: with mana value (?P<cap_after>.+?))? without paying its mana cost"
)
_CAST_CAP_RE = re.compile(
    r"(?:(?P<lit>\d+|x) or less|less than or equal to (?P<le>.+)|less than (?P<lt>.+))"
)
#: The bottom of the library in a random order -- the only rest a free-cast dig leaves (no ordering decision).
_CAST_REST_RE = re.compile(r"(?:then )?put the rest on the bottom of your library in a random order")


def _cast_cap(cap: str) -> Optional[dict]:
    """The `look_top_cast_free` mana-value params of a printed cap ("3 or less", "x or less", "less than x", "less than
    or equal to the greatest power among attacking creatures you control"), ``None`` when unreadable."""
    m = _CAST_CAP_RE.fullmatch(cap.strip())
    if m is None:
        return None
    if m.group("lit") is not None:
        return {"max_mana_value": MV_X_MARKER if m.group("lit") == MV_X_MARKER else int(m.group("lit"))}
    phrase = (m.group("le") or m.group("lt")).strip()
    below = m.group("lt") is not None
    if phrase == MV_X_MARKER:
        bound: "int | str | dict | None" = MV_X_MARKER
    elif phrase.isdigit():
        bound = int(phrase)
    else:
        bound = parse_amount_phrase(phrase)
        if not isinstance(bound, dict):
            return None
        bound = {"kind": "count_selector", "selector": bound}
    params: dict = {"max_mana_value": bound}
    if below:
        params["mana_value_below"] = True
    return params


def _parse_cast_dig(
    count: "int | str | dict", pick: "re.Match[str]", tails: list[str],
    match_tail: Callable[[str], Optional[list[EffectSpec]]],
) -> Optional[list[EffectSpec]]:
    """The dig whose pick is a free cast (Cosmic Cube, Kiora, Perception Bobblehead, Svella): one `look_top_cast_free`
    (`LookTopCastFreeEffect`), whose uncast cards go to the bottom in a random order. A land card cannot be cast (RULE
    305.1), so the engine offers only the spells; the rest sentence is mandatory and the tails stay ordinary clauses."""
    if not tails or _CAST_REST_RE.fullmatch(tails[0]) is None:
        return None
    params: dict = {"count": count}
    if pick.group("type"):
        params["criteria"] = dict(CARD_TYPE_CRITERIA[pick.group("type").lower()])
    if pick.group("cap") and pick.group("cap_after"):
        return None
    if pick.group("cap") or pick.group("cap_after"):
        cap = _cast_cap(pick.group("cap") or pick.group("cap_after"))
        if cap is None:
            return None
        params.update(cap)
    if (params.get("max_mana_value") == MV_X_MARKER) and count != "x":
        return None  # the bound's X is the dig's own count X
    specs = [EffectSpec("look_top_cast_free", params)]
    for tail in tails[1:]:
        effects = match_tail(tail)
        if effects is None:
            return None
        specs.extend(effects)
    return specs


def reads_dig_x(node: object) -> bool:
    """Whether a `card_query` dict carries the `MV_X_MARKER` bound anywhere (an ``"or"`` list nests them)."""
    if isinstance(node, dict):
        return any(reads_dig_x(v) for v in node.values())
    if isinstance(node, list):
        return any(reads_dig_x(v) for v in node)
    return node == MV_X_MARKER


def parse_dig(
    count: "int | str | dict", remainder: str, match_tail: Callable[[str], Optional[list[EffectSpec]]],
    reveal: bool = False,
) -> Optional[list[EffectSpec]]:
    """The `EffectSpec`s for a dig whose first sentence ("look at/reveal the top N cards of your
    library") was already read: ``remainder`` is every sentence after it. ``reveal`` is that sentence's verb: RULE
    701.20a, "reveal" shows every inspected card to all players (and `GameState.public_card_knowledge` keeps them
    known), "look at" shows them to the digger only."""
    sentences = [s.strip().rstrip(".") for s in _SENTENCE_SPLIT_RE.split(remainder) if s.strip()]
    if not sentences:
        return None
    selection, tails = sentences[0], sentences[1:]
    params: dict = {"count": count}

    cast_pick = _CAST_PICK_RE.fullmatch(selection)
    if cast_pick is not None:
        if reveal:
            return None  # `look_top_cast_free` has no reveal step: stay unclaimed rather than hide a reveal
        return _parse_cast_dig(count, cast_pick, tails, match_tail)
    pick = _PICK_OF_THEM_RE.fullmatch(selection)
    exile_pick = _EXILE_PICK_RE.fullmatch(selection) if pick is None else None
    rest_text: Optional[str]
    single_rest = False
    exile_rest = False
    shuffle_rest = False
    if exile_pick is not None:
        # RULE 406.3: the picked card goes to exile (face down when printed so); the window sentence after the rest is
        # parsed below. A bare "exile one" with no window is not claimed here (nothing reads the exiled card).
        criteria = parse_criteria(exile_pick.group("crit")) if exile_pick.group("crit") else {}
        if criteria is None or exile_pick.group("rest_group") == "the other":
            return None
        params.update(
            action="exile_face_down" if exile_pick.group("down") else "exile",
            max_picks=1, optional=bool(exile_pick.group("may")),
        )
        if criteria:
            params["criteria"] = criteria
        rest_text = exile_pick.group("rest")
    elif pick is not None:
        params.update(
            action=_ACTION_BY_DEST[pick.group("dest")],
            max_picks=int(pick.group("n")), optional=bool(pick.group("up_to") or pick.group("may")),
        )
        rest_text = pick.group("rest")
        single_rest = pick.group("rest_group") == "the other"
        exile_rest = pick.group("exile_rest") is not None
    else:
        sel = _SELECTION_RE.fullmatch(selection)
        if sel is None or (sel.group("verb") == "reveal") != bool(sel.group("andput")):
            return None
        quant = sel.group("quant")
        plural = quant in ("all", "any number of") or quant.startswith("up to")
        separate = None if plural else _SEPARATE_ITEMS_RE.fullmatch(sel.group("crit"))
        slots = None if plural or separate is not None or quant not in ("a", "an") else parse_pick_slots(sel.group("crit"))
        if slots is not None:
            # RULE 608.2c: one card per named slot, the pool being every card that fills some slot.
            criteria = {"or": slots}
            params["pick_slots"] = [dict(slot) for slot in slots]
        elif separate is not None:
            # "a creature card and/or a land card": at most one card per named type (RULE 205.2a), the engine's
            # `distinct_card_types` pick. Only real card types can be told apart this way.
            kinds = [separate.group("a"), separate.group("b")]
            if not set(kinds) <= _DISTINCT_TYPE_WORDS or kinds[0] == kinds[1]:
                return None
            criteria = {"type": kinds}
            params["distinct_card_types"] = True
        else:
            criteria = parse_criteria(sel.group("crit"), union_and=plural)
        if criteria is None:
            return None
        everything = quant in ("all", "any number of")
        optional = bool(sel.group("may")) or quant.startswith("up to") or quant == "any number of"
        if quant == "all" and sel.group("may"):
            return None
        action = _ACTION_BY_DEST[sel.group("dest")]
        if sel.group("verb") == "reveal" and not reveal and action == "library_to_hand":
            # RULE 701.20a: "look at the top N ... you may reveal a creature card from among them and put it into your
            # hand" shows only the picked card (the engine's reveal-the-pick hand action), not the whole window.
            action = REVEAL_PICK_TO_HAND_ACTION
        params.update(
            action=action,
            max_picks=(
                "all" if everything else int(quant.split()[-1]) if quant.startswith("up to")
                else len(kinds) if separate is not None else len(slots) if slots is not None else 1
            ),
            optional=optional,
        )
        if criteria:
            params["criteria"] = criteria
        rest_text = sel.group("rest")
        if sel.group("shuffle"):
            # RULE 701.24a / 401.2: "put ... onto the battlefield, then shuffle": the unpicked cards never left the
            # library, which is shuffled once the pick is done (Famished Worldsire, Through the Forest Gate).
            rest_text, shuffle_rest = None, True

    rest_dest = None
    if shuffle_rest:
        rest_dest = "library_shuffled"
    elif exile_rest:
        rest_dest = "exile"
    elif rest_text is None and tails and _SHUFFLE_REST_RE.fullmatch(tails[0]):
        rest_dest, tails = "library_shuffled", tails[1:]
    elif rest_text is None and tails and tails[0] == "exile the rest":
        rest_dest, tails = "exile", tails[1:]
    elif rest_text is None and tails and (rest_sentence := _REST_SENTENCE_RE.fullmatch(tails[0])) is not None:
        rest_text = rest_sentence.group("dest")
        single_rest = bool(rest_sentence.group("other"))
        tails = tails[1:]
    if single_rest:
        # RULE 609.3 / 401.4: choosing one of two leaves at most one card.
        # "The other" cannot stand for an arbitrary pile or an optional pick.
        if not (count == 2 and pick is not None and params["max_picks"] == 1 and not params["optional"]):
            return None
        if rest_text == "on the bottom of your library":
            # A singleton has no ordering decision; reuse the ordered-bottom
            # continuation, which already skips ordering fewer than two cards.
            rest_text += " in any order"
    if rest_text is not None:
        rest_dest = _rest_destination(rest_text)
    if pick is not None and pick.group("dest") == "into your graveyard" and rest_text is None and not tails:
        # RULE 401.2: looking and choosing one card does not reorder the
        # unchosen library cards (Soulcipher Board).
        rest_dest = "library_unchanged"
    if rest_dest is None:
        return None
    if reads_dig_x(params.get("criteria")) and count != "x":
        return None  # the bound's X is the dig's own count X (announced, or bound by "where X is ..."): no other X exists
    params["rest_destination"] = rest_dest
    if exile_pick is not None:
        # The window the exiled card is cast / played in: the next sentence, run once something was picked (RULE 608.2c).
        window = parse_pick_cast_window(tails[0], match_tail) if tails else None
        if window is None:
            return None
        params["placed_effects"] = [spec.to_dict() for spec in window]
        tails = tails[1:]

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
    if (pick is not None and params["action"] == "library_to_hand" and isinstance(count, (int, str))
            and rest_text == "on the bottom of your library in any order"):
        # RULE 401.4: an ordered bottom pile is the player's choice, not a
        # random permutation. The existing fixed-count hand dig owns that
        # two-stage selection and ordering continuation (Prophetic Bolt).
        if "else_effects" in params or reveal:
            return None  # (`look_top_select` has no reveal step either)
        return [EffectSpec("look_top_select", {
            "count": count, "select_count": params["max_picks"],
            "select_optional": params["optional"],
            "rest_destination": "library_bottom", "rest_order": "any",
        }), *specs]
    if reveal:
        params["reveal"] = True
    return [EffectSpec("inspect_top_choose", params), *specs]
