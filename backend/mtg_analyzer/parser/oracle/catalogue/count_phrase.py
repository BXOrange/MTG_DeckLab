"""Count phrases → structured selectors and count conditions (PAR-120).

"How many X" was spelled out in eleven phrase → selector tables (`_FOR_EACH_*`,
`_PT_CDA_*`, `_CONTROL_COUNT_*`, …) and one named branch per phrase in
`continuous.count_selector`. Here it is one grammar: the noun phrase
(`characteristic_phrase`, plural allowed) plus where the objects are —
"creatures you control", "lands your opponents control", "creature cards in your
graveyard", "cards in your hand" — becomes a structured selector::

    {"zone": "battlefield" | "graveyard" | "hand" | "exile" | "library",
     "of": "you" | "opponents" | "any",
     "filter": {<combat.matches_object_filter keys>},
     "distinct": "power" | "toughness" | "mana_value" | "name"}     # optional

which `continuous.count_selector` evaluates through the same filter every trigger
head and target phrase uses. On top of it, `parse_count_condition` reads the
comparator half of a leading "if": "you control three or more gates", "there are
seven or more creature cards in your graveyard", "an opponent controls more lands
than you". Anything unrecognised returns ``None``. Pure — no `game/` imports.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from .characteristic_phrase import parse_object_phrase, parse_qualifier

#: A count phrase's location suffix → the selector keys it sets. "Your opponents'"
#: and "all" scopes are sums over those players' zones.
_ZONE_SUFFIXES: list[tuple[str, dict[str, str]]] = [
    (" in your graveyard", {"zone": "graveyard", "of": "you"}),
    (" in the chosen player's graveyard", {"zone": "graveyard", "of": "chosen"}),
    (" in all graveyards", {"zone": "graveyard", "of": "any"}),
    (" in each graveyard", {"zone": "graveyard", "of": "any"}),
    (" in your opponents' graveyards", {"zone": "graveyard", "of": "opponents"}),
    (" in opponents' graveyards", {"zone": "graveyard", "of": "opponents"}),
    (" in each opponent's graveyard", {"zone": "graveyard", "of": "opponents"}),
    (" in your hand", {"zone": "hand", "of": "you"}),
    (" in the chosen player's hand", {"zone": "hand", "of": "chosen"}),
    (" in your library", {"zone": "library", "of": "you"}),
    (" in all players' hands", {"zone": "hand", "of": "any"}),
    (" you own in exile", {"zone": "exile", "of": "you"}),
    (" in exile", {"zone": "exile", "of": "any"}),
]

_OF_FOR_CONTROLLER = {"you": "you", "not_you": "opponents"}
_MODIFIED_ADJECTIVE = re.compile(r"\bmodified (?=(?:creature|permanent)s?\b)")
_ZONE_COUNTER_TAIL = re.compile(r" with (?P<q>an? [a-z+/\-0-9]+ counters? on (?:it|them))$")
_DIFFERENT = re.compile(r"\s+with different (?P<what>powers|toughnesses|names|mana values)")
_DISTINCT_KEYS = {
    "powers": "power", "toughnesses": "toughness", "names": "name", "mana values": "mana_value",
}
#: "on the battlefield" names every player's permanents; it sits either last
#: ("zombies on the battlefield") or before a tail ("creatures on the battlefield
#: with shadow" — Dauthi Warlord).
_ON_BATTLEFIELD = re.compile(r"\s+on the battlefield(?=\s|$)")
#: "creatures **named ~**" (Plague Rats) — the reference object's own name.
_NAMED_SOURCE = re.compile(r"\s+named ~(?=\s|$)")
#: "permanents you control **that are Spirits and/or enchantments**" (Katilda) —
#: a relative clause restating the head as a plural type list.
_THAT_ARE = re.compile(r"\s+that are (?P<what>[a-z/, ]+)$")
#: "tokens you control **that entered this turn**" (Ocelot Pride, Renewed
#: Solidarity) — the `entered_this_turn` filter key `combat.matches_object_filter`
#: already reads off `GameObject.entered_turn`. Always the last tail.
_ENTERED_THIS_TURN = re.compile(r"\s+that entered (?:the battlefield )?this turn$")
#: "creatures **blocking it**" / "…that share a creature type with **it**" — counted against the object
#: a pronoun names (`blocking_source` / `shares_creature_type_with_reference`); the caller says which
#: object that is (the amount's ``reference``).
#: "cards in exile **that have an adventure**" (Howling Galefang) — the `has_adventure` filter key.
_HAS_ADVENTURE = re.compile(r"\s+that (?:has|have) an adventure$")
_BLOCKING_IT = re.compile(r"\s+blocking (?:it|~)$")
#: RULE 506.3 / 509.1a: the combat relations a source names *as itself* (``~``), read at the end of combat
#: step (RULE 511.1) while the blocks are still on the board — "creatures blocking ~" (The Wretched), "creatures
#: blocking or blocked by ~" (Greater Werewolf, Kjeldoran Frostbeast), "creatures blocked by ~" (Wall of Nets) and,
#: over the turn's history, "creature that blocked or was blocked this turn" (Heat Stroke) and "creatures that
#: blocked ~ this turn" (Joven's Ferrets). Only ``~``: a pronoun's referent depends on the trigger head, which a
#: count phrase cannot see. Each maps onto its `combat.matches_object_filter` key.
COMBAT_RELATION_TAILS: tuple[tuple["re.Pattern[str]", str], ...] = (
    (re.compile(r"\s+blocking ~$"), "blocking_source"),
    (re.compile(r"\s+blocking or blocked by ~$"), "blocking_or_blocked_by_source"),
    (re.compile(r"\s+blocked by ~$"), "blocked_by_source"),
    (re.compile(r"\s+that blocked or (?:was|were) blocked this turn$"), "blocked_or_was_blocked_this_turn"),
    (re.compile(r"\s+that blocked ~ this turn$"), "blocked_source_this_turn"),
)
_SHARES_TYPE_WITH_IT = re.compile(r"\s+that shares? a creature type with (?:it|~)$")
# One noun phrase can name two disjoint zones (Crackling Drake / Huskburster
# Swarm). Each half keeps the same filter; summing is safe because an object
# cannot be in exile and a graveyard at the same time (RULE 400.1).
_TWO_ZONES = re.compile(
    r"^(?P<head>.+?) (?P<first>you own in exile|in exile|in your graveyard)"
    r" and (?P<second>in exile|in your graveyard)$"
)

_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10,
}
NUMBER_WORD_PATTERN = r"(?:\d+|" + "|".join(_NUMBER_WORDS) + r")"


def number_value(text: str) -> int:
    return int(text) if text.isdigit() else _NUMBER_WORDS[text]


def parse_count_phrase(text: str) -> Optional[dict[str, Any]]:
    """The words after "for each" / "the number of" → a structured selector, or ``None``."""
    text = text.strip().lower()
    if not text:
        return None  # an empty phrase would count every permanent
    doors = _UNLOCKED_DOORS.match(text)
    if doors is not None:
        return _door_selector(doors.group("phrase"), {"aggregate": "sum", "value": "unlocked_doors"})
    names = _DOOR_NAMES.match(text)
    if names is not None:
        return _door_selector(names.group("phrase"), {"distinct": "door_name"})
    two_zones = _TWO_ZONES.fullmatch(text)
    if two_zones is not None:
        head = two_zones.group("head")
        first = parse_count_phrase(f"{head} {two_zones.group('first')}")
        second = parse_count_phrase(f"{head} {two_zones.group('second')}")
        if first is None or second is None or first.get("zone") == second.get("zone"):
            return None
        return {"terms": [first, second]}
    name_tail = re.search(r" with the same name as (.+)$", text)
    name_extra = None
    if name_tail:
        name_extra = parse_qualifier('the same name as ' + name_tail[1])
        if name_extra is not None:
            text = text[:name_tail.start()]
    selector: dict[str, Any] = {}
    extra: dict[str, Any] = dict(name_extra or {})
    # PAR-153: RULE 700.9 "attacking modified creature you control" (Mirror-Style Master) -- a permanent with a counter,
    # Equipment or controlled Aura on it (`continuous.is_modified`). Read here, in a live count/iteration, and not in
    # `characteristic_phrase`'s shared adjectives: a trigger head ("whenever a modified creature you control dies") would
    # have to judge it from last-known information, which the trigger filters do not carry.
    modified = _MODIFIED_ADJECTIVE.search(text)
    if modified is not None:
        extra["modified"] = True
        text = (text[: modified.start()] + text[modified.end():]).strip()
    if text.endswith(" other than ~"):
        extra["not_reference"] = True
        text = text[:-len(" other than ~")]
    if text.startswith("other "):
        # "the number of other Rats on the battlefield" (Pestilence Rats): the
        # counting object's own source is excluded (the `another` idiom).
        extra["not_reference"] = True
        text = text[len("other "):]
    named = _NAMED_SOURCE.search(text)
    if named is not None:
        extra["named_as_reference"] = True
        text = (text[: named.start()] + text[named.end():]).strip()
    entered = _ENTERED_THIS_TURN.search(text)
    if entered is not None:
        extra["entered_this_turn"] = True
        text = text[: entered.start()].strip()
    adventure = _HAS_ADVENTURE.search(text)
    if adventure is not None:
        extra["has_adventure"] = True
        text = text[: adventure.start()].strip()
    for tail, relation_key in COMBAT_RELATION_TAILS:
        relation = tail.search(text)
        if relation is not None:
            extra[relation_key] = True
            text = text[: relation.start()].strip()
            break
    blocking = _BLOCKING_IT.search(text)
    if blocking is not None:
        extra["blocking_source"] = True
        text = text[: blocking.start()].strip()
    shares = _SHARES_TYPE_WITH_IT.search(text)
    if shares is not None:
        extra["shares_creature_type_with_reference"] = True
        text = text[: shares.start()].strip()
    that_are = _THAT_ARE.search(text)
    if that_are is not None:
        restated = parse_object_phrase(that_are.group("what"), plural=True)
        if restated is None or restated[1] is not None:
            return None
        extra.update(restated[0])
        text = text[: that_are.start()].strip()
    different = _DIFFERENT.search(text)
    if different is not None:
        selector["distinct"] = _DISTINCT_KEYS[different.group("what")]
        text = (text[: different.start()] + text[different.end():]).strip()
    # PAR-153: "creature cards you own in exile **with a memory counter on it**" (Altaïr) — a counter qualifier
    # that trails the zone words; lifted off and ANDed into the filter like the other trailing tails.
    zone_counter = _ZONE_COUNTER_TAIL.search(text)
    if zone_counter is not None and any(text[: zone_counter.start()].endswith(z) for z, _ in _ZONE_SUFFIXES):
        qualifier = parse_qualifier(zone_counter.group("q"))
        if qualifier is None:
            return None
        extra.update(qualifier)
        text = text[: zone_counter.start()]
    linked = re.fullmatch(r"(?P<head>.+?) exiled with (?:~|it)", text)
    if linked:
        head = linked['head']
        own = head.endswith(' you own')
        if own:
            head = head[:-len(' you own')]
        parsed = parse_object_phrase(head, plural=True)
        if parsed is None or parsed[1] is not None:
            return None
        filt = _merge_filters(parsed[0], extra)
        if filt is None:
            return None
        return {**selector, 'zone': 'exile', 'of': 'you' if own else 'any',
                'linked_exile': True, **({'filter': filt} if filt else {})}
    for suffix, keys in _ZONE_SUFFIXES:
        if text.endswith(suffix):
            parsed = parse_object_phrase(text[: -len(suffix)], plural=True)
            if parsed is None or parsed[1] is not None:
                return None  # a controller tail contradicts the zone's owner
            selector.update(keys)
            filt = _merge_filters(parsed[0], extra)
            if filt is None:
                return None
            if filt:
                selector["filter"] = filt
            return selector
    # PAR-153: "the number of creatures defending player controls" (Nacatl War-Pride) — the player the source is
    # attacking (RULE 506.2), read off its ``combat_defender`` when the count is taken.
    defending_control_tail = " defending player controls"
    if text.endswith(defending_control_tail):
        parsed = parse_object_phrase(text[:-len(defending_control_tail)], plural=True)
        if parsed is None or parsed[1] is not None:
            return None
        filt = _merge_filters(parsed[0], extra)
        if filt is None:
            return None
        return {"zone": "battlefield", "of": "defending", **({"filter": filt} if filt else {})}
    chosen_control_tail = " the chosen player controls"
    if text.endswith(chosen_control_tail):
        parsed = parse_object_phrase(text[:-len(chosen_control_tail)], plural=True)
        if parsed is None or parsed[1] is not None:
            return None
        filt = _merge_filters(parsed[0], extra)
        if filt is None:
            return None
        return {"zone": "battlefield", "of": "chosen", **({"filter": filt} if filt else {})}
    text = _ON_BATTLEFIELD.sub("", text, count=1)
    parsed = parse_object_phrase(text, plural=True)
    if parsed is None:
        return None
    filt, controller = parsed
    filt = _merge_filters(filt, extra)
    if filt is None:
        return None
    selector.update({"zone": "battlefield", "of": _OF_FOR_CONTROLLER.get(controller or "", "any")})
    if filt:
        selector["filter"] = filt
    return selector


def _merge_filters(base: dict[str, Any], extra: dict[str, Any]) -> Optional[dict[str, Any]]:
    """AND two filter fragments, or ``None`` when they constrain the same key
    ("creatures that are Fungi" is fine; "creatures that are artifacts" would
    need both a ``card_type`` and a ``card_type_any`` — refuse rather than guess)."""
    if any(k in base for k in extra):
        return None
    return {**base, **extra}


#: The quantity words before the counted noun → the comparison bounds they mean.
#: Each returns ``(min, max, other)`` where ``other`` ("another") excludes the
#: ability's own source from the count.
def _quantity(text: str) -> Optional[tuple[Optional[int], Optional[int], bool, str]]:
    """Leading quantity words → ``(min, max, another, rest)``, or ``None``."""
    patterns: list[tuple[str, Any]] = [
        (rf"^(?P<n>{NUMBER_WORD_PATTERN}) or more ", lambda n: (n, None)),
        (rf"^at least (?P<n>{NUMBER_WORD_PATTERN}) ", lambda n: (n, None)),
        (rf"^(?P<n>{NUMBER_WORD_PATTERN}) or (?:fewer|less) ", lambda n: (None, n)),
        (rf"^at most (?P<n>{NUMBER_WORD_PATTERN}) ", lambda n: (None, n)),
        (rf"^exactly (?P<n>{NUMBER_WORD_PATTERN}) ", lambda n: (n, n)),
        (rf"^more than (?P<n>{NUMBER_WORD_PATTERN}) ", lambda n: (n + 1, None)),
        (rf"^fewer than (?P<n>{NUMBER_WORD_PATTERN}) ", lambda n: (None, n - 1)),
    ]
    for pattern, bounds in patterns:
        m = re.match(pattern, text)
        if m is not None:
            low, high = bounds(number_value(m.group("n")))
            return low, high, False, text[m.end():]
    m = re.match(r"^(?:a|an) ", text)
    if m is not None:
        return 1, None, False, text[m.end():]
    if text.startswith("another "):
        return 1, None, True, text[len("another "):]
    if text.startswith("no "):
        return None, 0, False, text[len("no "):]
    return None


_CONTROL = re.compile(r"^you control (?P<rest>.+)$")
#: "you own a card in exile that has an adventure" — ownership, so the count is over *your* zone.
_OWN = re.compile(r"^you own (?P<rest>.+)$")
_THERE_ARE = re.compile(r"^there (?:are|is) (?P<rest>.+)$")
_OPPONENT_MORE = re.compile(r"^an opponent controls more (?P<phrase>.+?) than you$")
_YOU_MOST = re.compile(r"you control (?P<direction>more|fewer) (?P<phrase>.+?) than each other player")


def parse_count_condition(text: str) -> Optional[dict[str, Any]]:
    """A condition phrase about how many objects exist → a `control_count` /
    `opponent_has_more` condition dict, or ``None``.

    "you control `<quantity>` `<phrase>`" counts objects *you* control ("you
    control" is the scope, so the phrase names none); "there are `<quantity>`
    `<phrase>`" counts the phrase's own location ("… in your graveyard").
    """
    text = text.strip().lower().rstrip(".")
    linked_exists = re.fullmatch(r"(?P<head>an? .+?) (?:is|are) exiled with (?P<source>~|it)", text)
    if linked_exists:
        text = f"there is {linked_exists['head']} exiled with {linked_exists['source']}"
    m = _YOU_MOST.fullmatch(text)
    if m is not None:
        selector = parse_count_phrase(m['phrase'])
        if selector is None or selector.get('of') != 'any' or selector.get('zone') != 'battlefield':
            return None
        return {'kind': 'you_have_most' if m['direction'] == 'more' else 'you_have_fewest',
                'selector': {**selector, 'of': 'you'}}
    m = _OPPONENT_MORE.match(text)
    if m is not None:
        selector = parse_count_phrase(m.group("phrase"))
        if selector is None or selector.get("of") != "any" or selector.get("zone") != "battlefield":
            return None
        return {"kind": "opponent_has_more", "selector": {**selector, "of": "you"}}
    control = _CONTROL.match(text)
    there = _THERE_ARE.match(text)
    own = _OWN.match(text)
    if control is None and there is None and own is None:
        return None
    rest = (control or there or own).group("rest")
    quantity = _quantity(rest)
    if quantity is None:
        return None
    low, high, another, phrase = quantity
    selector = parse_count_phrase(phrase)
    if selector is None:
        return None
    if control is not None:
        if selector.get("zone") != "battlefield" or selector.get("of") != "any":
            return None  # "you control" already fixed the scope
        selector["of"] = "you"
    elif own is not None:
        if selector.get("zone") == "battlefield":
            return None  # "you own" counts cards in a zone, never permanents
        selector["of"] = "you"
    elif selector.get("zone") == "battlefield":
        pass  # "there are 4 or more creatures on the battlefield": any player's
    if another:
        selector["filter"] = {**selector.get("filter", {}), "not_reference": True}
    condition: dict[str, Any] = {"kind": "control_count", "selector": selector}
    if low is not None:
        condition["min"] = low
    if high is not None:
        condition["max"] = high
    return condition


#: A term of an amount expression that is not "the number of `<count phrase>`":
#: values *among* a group rather than how many objects it holds.
#: RULE 709.5 (MEC-111): "the number of unlocked doors among Rooms you control" (Misty Salon) — the Rooms' designations
#: summed — and "different names among unlocked doors of Rooms you control" (Promising Stairs).
_UNLOCKED_DOORS = re.compile(r"^unlocked doors among (?P<phrase>.+)$")
_DOOR_NAMES = re.compile(r"^different names among unlocked doors of (?P<phrase>.+)$")
_AMONG_DISTINCT = re.compile(
    r"^the number of (?P<what>card types|colors) among (?P<phrase>.+)$"
)
_DISTINCT_AMONG_KEYS = {"card types": "card_type", "colors": "color"}
_AGGREGATE = re.compile(
    r"^the (?P<agg>greatest|total) (?P<value>mana value|power|toughness) "
    r"(?:among|of) (?P<phrase>.+)$"
)
_AGGREGATE_KEYS = {"greatest": "max", "total": "sum"}
_COUNTERS_ON = re.compile(
    r"^the number of (?:(?P<kind>\+1/\+1|-1/-1|[a-z]+) )?counters on (?P<on>.+)$"
)
_NUMBER_OF = re.compile(r"^the (?:total )?number of (?P<phrase>.+)$")
_DEVOTION_TERM = re.compile(r"^your devotion to (?P<color>white|blue|black|red|green)$")
#: RULE 700.5: devotion *is* the count of a colour's mana symbols in the mana
#: costs of permanents you control — Primalcrux prints the definition.
_MANA_SYMBOLS_TERM = re.compile(
    r"^the number of (?P<color>white|blue|black|red|green) mana symbols in the mana costs "
    r"of permanents you control$"
)
_MANA_SYMBOLS_IN_ZONE = re.compile(
    r"^the number of (?P<color>white|blue|black|red|green) mana symbols in the mana costs "
    r"of (?P<phrase>.+)$"
)
_MANA_COLOR_LETTERS = {"white": "W", "blue": "U", "black": "B", "red": "R", "green": "G"}
#: "the number of differently named lands you control" (Awakened Amalgam) —
#: the ``distinct: name`` reading "lands you control with different names" has.
_DIFFERENTLY_NAMED = re.compile(r"^the number of differently named (?P<phrase>.+)$")
#: Terms with no noun phrase to parse → the named `continuous.count_selector`
#: they already are.
_NAMED_TERMS: dict[str, str] = {
    "the number of basic land types among lands you control": "basic_land_types_among_lands_you_control",
    "your life total": "your_life_total",
    "the greatest mana value among your commanders": "greatest_commander_mana_value",
    "the greatest mana value of a commander you own on the battlefield or in the command zone":
        "greatest_commander_mana_value",
    "the greatest mana value among commanders you own on the battlefield or in the command zone":
        "greatest_commander_mana_value",
    # `GameState.life_gained_this_turn` (Fortifying Draught) — a turn total, no noun phrase.
    "the amount of life you gained this turn": "life_gained_this_turn",
    "the amount of life you lost this turn": "life_lost_this_turn",
    "the number of experience counters you have": "experience_counters_you_have",
    # RULE 702.108a: the colours of mana spent on the spell that is resolving (Radiant Flames' "where X is …").
    "the number of colors of mana spent to cast this spell": "converge",
}
#: "the sacrificed creature's power" (Fling, Altar of Dementia, Ghoulcaller Gisa) — what the ability's own
#: sacrifice (a cost, or "you may sacrifice a creature. When you do, …") stamped on its source
#: (`RulesEngine.note_sacrificed` → `continuous.count_selector`'s ``sacrificed_cost_*``).
SACRIFICED_TERM = r"the sacrificed (?:creature|permanent|artifact|land)'?s (?:power|toughness|mana value)"
_SACRIFICED = re.compile(r"^the sacrificed (?:creature|permanent|artifact|land)'?s (?P<what>power|toughness|mana value)$")
#: "`<N>` plus …" (Allosaurus Rider) and "twice …" (Territorial Maro).
_PLUS_PREFIX = re.compile(rf"^(?P<n>{NUMBER_WORD_PATTERN}) plus (?P<rest>.+)$")
_TWICE_PREFIX = "twice "
#: Where one term ends and the next begins: "X plus the number of Y".
_TERM_SPLIT = re.compile(r" plus (?=the |your )")


def _door_selector(phrase: str, measure: dict[str, Any]) -> Optional[dict[str, Any]]:
    """The Rooms ``phrase`` names, measured by their unlocked doors."""
    selector = parse_count_phrase(phrase)
    if selector is None or "distinct" in selector or selector.get("filter") != {"subtype": "room"}:
        return None
    return {**selector, **measure}


def parse_amount_term(text: str) -> "Optional[str | dict[str, Any]]":
    """One quantity — "the number of `<count phrase>`", "the greatest mana value
    among `<phrase>`", "the number of fade counters on it", "your life total" —
    → a `continuous.count_selector` argument, or ``None``."""
    text = text.strip().lower()
    if text in _NAMED_TERMS:
        return _NAMED_TERMS[text]
    m = _SACRIFICED.match(text)
    if m is not None:
        return "sacrificed_cost_" + m.group("what").replace(" ", "_")
    m = _DEVOTION_TERM.match(text) or _MANA_SYMBOLS_TERM.match(text)
    if m is not None:
        return f"devotion_to_{m.group('color')}"
    m = _MANA_SYMBOLS_IN_ZONE.match(text)
    if m is not None:
        selector = parse_count_phrase(m.group("phrase"))
        if selector is None or "terms" in selector:
            return None
        return {**selector, "aggregate": "sum", "value": "mana_symbols",
                "color": _MANA_COLOR_LETTERS[m.group("color")]}
    m = _DIFFERENTLY_NAMED.match(text)
    if m is not None:
        selector = parse_count_phrase(m.group("phrase"))
        if selector is None or "distinct" in selector:
            return None
        return {**selector, "distinct": "name"}
    m = _AMONG_DISTINCT.match(text)
    if m is not None:
        selector = parse_count_phrase(m.group("phrase"))
        if selector is None or "distinct" in selector:
            return None
        return {**selector, "distinct": _DISTINCT_AMONG_KEYS[m.group("what")]}
    m = _AGGREGATE.match(text)
    if m is not None:
        selector = parse_count_phrase(m.group("phrase"))
        if selector is None or "distinct" in selector:
            return None
        return {
            **selector,
            "aggregate": _AGGREGATE_KEYS[m.group("agg")],
            "value": m.group("value").replace(" ", "_"),
        }
    m = _COUNTERS_ON.match(text)
    if m is not None:
        kind = m.group("kind")
        if m.group("on") in ("it", "~"):
            return {"counters_on": "source", **({"kind": kind} if kind else {})}
        selector = parse_count_phrase(m.group("on"))
        if selector is None or "distinct" in selector:
            return None
        selector.update({"aggregate": "sum", "value": "counters"})
        if kind:
            selector["counter_kind"] = kind
        return selector
    m = _NUMBER_OF.match(text)
    if m is not None:
        return parse_count_phrase(m.group("phrase"))
    return None


def parse_amount_phrase(text: str) -> "Optional[str | dict[str, Any]]":
    """A whole "equal to …" amount → a `continuous.count_selector` argument.

    ``amount := [<N> "plus "] ["twice "] term (" plus " term)*`` — a lone term is
    returned as-is (so every phrase the plain count grammar already covered keeps
    its exact selector); anything with arithmetic becomes ``{"terms": [...],
    "times": k, "plus": n}`` (`continuous._count_expression`). ``None`` if any
    term is unknown — a characteristic-defining ability reading an unmodeled
    quantity would silently define the creature as 0/0.
    """
    text = text.strip().lower().rstrip(".")
    plus = 0
    m = _PLUS_PREFIX.match(text)
    if m is not None:
        plus, text = number_value(m.group("n")), m.group("rest")
    times = 1
    if text.startswith(_TWICE_PREFIX):
        times, text = 2, text[len(_TWICE_PREFIX):]
    terms = [parse_amount_term(part) for part in _TERM_SPLIT.split(text)]
    if not terms or any(term is None for term in terms):
        return None
    if len(terms) == 1 and times == 1 and plus == 0:
        return terms[0]
    expression: dict[str, Any] = {"terms": terms}
    if times != 1:
        expression["times"] = times
    if plus:
        expression["plus"] = plus
    return expression
