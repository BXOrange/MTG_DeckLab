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
_ZONE_COUNTER_TAIL = re.compile(r" with (?P<q>(?:an? )?[a-z+/\-0-9]+ counters? on (?:it|them))$")
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
#: RULE 201.5: a token's quoted "cards **named <<creating card>>**" (Sound the Call) -- the creating card's printed name,
#: kept by `normalize` as a literal because the bare ``~`` of that ability is the token. Matched exactly (RULE 201.2).
_NAMED_LITERAL = re.compile(r"\s+named <<(?P<name>[a-z0-9' -]+)>>(?=\s|$)")
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
#: PAR-284 / RULE 301.5, 303.4: "the number of Equipment / Auras **attached to ~ / it**" -- attachments whose host is the
#: reference object (`attached_to_reference`, read by `combat.matches_object_filter`).
_ATTACHED_TO_REFERENCE = re.compile(r"\s+attached to (?:it|~)$")
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
    # PAR-283: the larger counts real cards spell out ("thirteen or more creatures", "thirty or more artifacts").
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
    "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30,
}
NUMBER_WORD_PATTERN = r"(?:\d+|" + "|".join(_NUMBER_WORDS) + r")"


def number_value(text: str) -> int:
    return int(text) if text.isdigit() else _NUMBER_WORDS[text]


#: RULE 105.2 / 202.2: "permanents you control **that are exactly two colors**" (Niv-Mizzet, Guildpact) -- the
#: `color_count` filter key `combat.matches_object_filter` reads.
_EXACTLY_N_COLORS = re.compile(rf"\s+that are exactly (?P<n>{NUMBER_WORD_PATTERN}) colors?$")


_DIFFERENTLY_NAMED_PREFIX = "differently named "


#: RULE 205.3m: the relative clause that turns a creature count into a largest-shared-creature-type count.
_SHARE_TYPE_TAILS = (" that share a creature type", " that have a creature type in common")
#: "the greatest number of creatures you control that have a creature type in common" (Basalt Ravager, Skemfar Shadowsage)
#: is the same largest-group count, said with its own superlative.
_GREATEST_SHARED_NUMBER = re.compile(r"^the greatest number of (?P<phrase>.+)$")


#: PAR-284 milestone 17 (RULE 102.2 / 608.2h): player-scoped count phrases -- "opponents who control more lands than you",
#: "opponent who was dealt damage this turn", "your opponents with 4 or more cards in hand", "opponent who has 3 or more
#: poison counters", "opponent who drew 2 or more cards this turn" -> ``{"players": "opponents" | "players", "where":
#: {"kind": ..., ...}}``, the selector `game/player_counts.players_matching_count` evaluates. `parse_count_phrase` tries it
#: first, so "for each ...", "the number of ..." and "where X is ..." all reach it.
#: "opponent" / "opponents" / "player" / "players", with the optional "your" the "the number of" spelling carries.
_SUBJECT = r"^(?:your )?(?P<who>opponents?|players?)"
_REL = r"(?: (?:who|that))"
#: The predicate tail -> the `player_counts._PREDICATES` row it names. Each pattern captures what its row needs.
_TAILS: list[tuple["re.Pattern[str]", str]] = [
    (re.compile(rf"{_REL} (?:was|were) dealt (?P<combat>combat )?damage this turn$"), "dealt_damage_this_turn"),
    (re.compile(rf"{_REL} controls? (?P<compare>more|fewer) (?P<what>.+) than you(?: do)?$"), "controls_compared"),
    (re.compile(rf"(?:{_REL} (?:has|have)|(?: with)) (?P<n>{NUMBER_WORD_PATTERN}) or more cards in (?:their )?hand$"), "hand_size"),
    (re.compile(rf"{_REL} (?:has|have) (?P<n>{NUMBER_WORD_PATTERN}) or more (?P<counter>[a-z]+) counters?$"), "counters"),
    (re.compile(rf"{_REL} drew (?P<n>{NUMBER_WORD_PATTERN}) or more cards this turn$"), "drew_this_turn"),
    (re.compile(
        rf"{_REL} had (?P<n>{NUMBER_WORD_PATTERN}) or more lands enter the battlefield under their control this turn$"),
     "lands_entered_this_turn"),
]


def parse_players_matching(text: str) -> Optional[dict[str, Any]]:
    """A "<opponents|players> who <predicate>" count phrase -> its player-count selector, or ``None``."""
    subject = re.match(_SUBJECT, text)
    if subject is None:
        return None
    tail = text[subject.end():]
    scope = "opponents" if subject.group("who").startswith("opponent") else "players"
    for pattern, kind in _TAILS:
        m = pattern.match(tail)
        if m is None:
            continue
        where: dict[str, Any] = {"kind": kind}
        groups = m.groupdict()
        if kind == "dealt_damage_this_turn":
            where["combat"] = bool(groups["combat"])
        elif kind == "controls_compared":
            if scope != "opponents":
                return None  # "than you" compares against the controller: only an opponent scope reads naturally
            selector = parse_count_phrase(f"{groups['what']} you control")
            if (not isinstance(selector, dict) or selector.get("of") != "you" or selector.get("zone") != "battlefield"
                    or {"distinct", "aggregate", "terms", "counters_on", "players"} & set(selector)):
                return None
            where.update(compare=groups["compare"], selector=selector)
        else:
            where["min"] = number_value(groups["n"])
            if kind == "counters":
                where["counter"] = groups["counter"]
        return {"players": scope, "where": where}
    return None


def parse_count_phrase(text: str) -> Optional[dict[str, Any]]:
    """The words after "for each" / "the number of" → a structured selector, or ``None``."""
    text = text.strip().lower()
    if not text:
        return None  # an empty phrase would count every permanent
    players = parse_players_matching(text)
    if players is not None:
        return players
    # RULE 201.2: "differently named lands you control" counts distinct names -- the same selector as
    # "lands you control with different names" (Astute Terraformer, Deep Space Scan).
    if text.startswith(_DIFFERENTLY_NAMED_PREFIX):
        inner = parse_count_phrase(text[len(_DIFFERENTLY_NAMED_PREFIX):])
        if inner is None or "distinct" in inner or "terms" in inner:
            return None
        return {**inner, "distinct": "name"}
    # PAR-318 / RULE 205.3m: "creatures ... that share a creature type" is the size of the largest group of the counted
    # objects with one creature type in common (Graxiplon), a selector-level ``share``.
    share_tail = next((tail for tail in _SHARE_TYPE_TAILS if text.endswith(tail)), None)
    if share_tail is not None:
        inner = parse_count_phrase(text[:-len(share_tail)])
        if inner is None or {"distinct", "aggregate", "terms", "counters_on", "share"} & set(inner):
            return None
        return {**inner, "share": "creature_type"}
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
    literal = _NAMED_LITERAL.search(text)
    if literal is not None:
        extra["name"] = literal.group("name")
        text = (text[: literal.start()] + text[literal.end():]).strip()
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
    attached = _ATTACHED_TO_REFERENCE.search(text) if " with " not in text else None  # "... with an X attached to it" is a `has_attachment` qualifier
    if attached is not None:
        if extra.get("not_reference"):
            # "... attached to ~ other than ~" excludes the *granting Aura*, not the host (Animal Friend); the one
            # reference this filter has is the host, so the exclusion cannot be stated.
            return None
        extra["attached_to_reference"] = True
        text = text[: attached.start()].strip()
    shares = _SHARES_TYPE_WITH_IT.search(text)
    if shares is not None:
        extra["shares_creature_type_with_reference"] = True
        text = text[: shares.start()].strip()
    exactly = _EXACTLY_N_COLORS.search(text)
    if exactly is not None:
        extra["color_count"] = number_value(exactly.group("n"))
        text = text[: exactly.start()].strip()
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
        counter_text = zone_counter.group("q")
        if not counter_text.startswith(("a ", "an ")):
            # PAR-284 milestone 18: "cards you own in exile with study counters on them" (Kianne) -- the bare plural
            # means "at least one study counter", the article form the qualifier grammar reads.
            counter_text = "a " + counter_text.replace(" counters on them", " counter on it").replace(" counter on them", " counter on it")
        qualifier = parse_qualifier(counter_text)
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
#: PAR-245: "your opponents control no creatures" -- the collective reading only for "no" ("an opponent controls a
#: creature" would need a per-opponent reading this grammar does not express).
_OPPONENTS_CONTROL_NO = re.compile(r"^your opponents control no (?P<phrase>.+)$")
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
    no_opponent_permanents = _OPPONENTS_CONTROL_NO.fullmatch(text)
    if no_opponent_permanents is not None:
        # RULE 102.2: "your opponents control no creatures" counts every opponent's permanents together (Erebos's Titan).
        selector = parse_count_phrase(no_opponent_permanents.group("phrase"))
        if selector is None or selector.get("zone") != "battlefield" or selector.get("of") != "any":
            return None
        return {"kind": "control_count", "selector": {**selector, "of": "opponents"}, "max": 0}
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
    r"^the number of (?P<what>card types|permanent types|colors|creature types|different mana values|different powers"
    r"|different toughnesses|different color pairs) among (?P<phrase>.+)$"
)
#: PAR-284 milestone 18 / RULE 702: "the number of abilities from among flying, first strike, ..., and vigilance found
#: among creatures you control" (Odric, Blood-Cursed) -- each listed ability counts once however many creatures have it.
_ABILITIES_AMONG = re.compile(r"^the number of abilities from among (?P<list>[a-z, ]+?),? and (?P<last>[a-z ]+) found among (?P<phrase>.+)$")
#: RULE 601.2i: "... among permanents you control **and spells you've cast this turn**" adds the cast spells' values.
_AND_SPELLS_CAST = " and spells you've cast this turn"
#: RULE 202.3: "different mana values" counts distinct mana values (`continuous._DISTINCT_KEYS`), the others distinct
#: members of a per-object set (`continuous._DISTINCT_SET_KEYS`).
_DISTINCT_AMONG_KEYS = {
    "card types": "card_type", "permanent types": "permanent_type", "different color pairs": "color_pair", "colors": "color", "creature types": "creature_type", "different mana values": "mana_value",
    # RULE 208.1 / 209.1: distinct power / toughness values (Celebrate the Harvest, Rival's Duel-style counts).
    "different powers": "power", "different toughnesses": "toughness",
}
_AGGREGATE = re.compile(
    r"^the (?P<agg>greatest|total) (?P<value>mana value|power and/or toughness|power|toughness) "
    r"(?:among|of) (?P<phrase>.+)$"
)
_AGGREGATE_KEYS = {"greatest": "max", "total": "sum"}
_COUNTERS_ON = re.compile(
    r"^the number of (?:(?P<kind>\+1/\+1|-1/-1|[a-z]+) )?counters (?:on|among) (?P<on>.+)$"
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
    "the number of times you descended this turn": "times_descended_this_turn",  # RULE 700.11, The Mycotyrant
    "the number of card types among spells you've cast this turn": "card_types_among_spells_cast_this_turn",
    "the number of colors among spells you've cast this turn": "colors_among_spells_cast_this_turn",
    "the number of card types among permanents you've sacrificed this turn": "card_types_among_permanents_sacrificed_this_turn",
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
    "the amount of {e} you have": "energy_counters_you_have",  # PAR-284 / RULE 107.14 (Razorfield Ripper)
    "the number of dilemmas you've faced this turn": "dilemmas_faced_this_turn",  # RULE 700.17
    "the number of opponents you attacked this turn": "opponents_attacked_this_turn",  # Battlefront
    "the number of creatures attacking you": "creatures_attacking_you",  # PAR-284 / RULE 506.2 (Sentry Bot)
    # RULE 702.179 (speed) / RULE 903.8 (commander tax): a player's own speed and the greatest {2}-per-cast tax among
    # the commanders they have cast (`continuous.count_selector`).
    "your speed": "your_speed",
    "your highest commander tax among your commanders": "highest_commander_tax",
    "the number of opponents being attacked": "players_being_attacked",  # PAR-284 / RULE 506.2 (Dimir Strandcatcher)
    # PAR-314 / RULE 702.33d + 702.33e: the Kicker/Multikicker payment count on the object the ability belongs to
    # ("where X is the number of times ~ was kicked", "equal to twice the number of times it was kicked").
    "the number of times it was kicked": "source_kicker_count",
    "the number of times ~ was kicked": "source_kicker_count",
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
    m = _ABILITIES_AMONG.match(text)
    if m is not None:
        selector = parse_count_phrase(m.group("phrase"))
        listed = [part.strip() for part in m.group("list").split(",") if part.strip()] + [m.group("last").strip()]
        if selector is None or "distinct" in selector or selector.get("zone") != "battlefield" or len(set(listed)) != len(listed):
            return None
        return {**selector, "distinct": "keyword", "keywords": listed}
    m = _AMONG_DISTINCT.match(text)
    if m is not None:
        phrase = m.group("phrase")
        with_spells = m.group("what") in ("colors", "card types") and phrase.endswith(_AND_SPELLS_CAST)
        if with_spells:
            phrase = phrase[: -len(_AND_SPELLS_CAST)]
        selector = parse_count_phrase(phrase)
        if selector is None or "distinct" in selector:
            return None
        return {**selector, "distinct": _DISTINCT_AMONG_KEYS[m.group("what")], **({"with_spells_cast_this_turn": True} if with_spells else {})}
    m = _AGGREGATE.match(text)
    if m is not None:
        selector = parse_count_phrase(m.group("phrase"))
        if selector is None or "distinct" in selector:
            return None
        return {
            **selector,
            "aggregate": _AGGREGATE_KEYS[m.group("agg")],
            "value": m.group("value").replace(" and/or ", "_or_").replace(" ", "_"),
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
    m = _GREATEST_SHARED_NUMBER.match(text)
    if m is not None:
        selector = parse_count_phrase(m.group("phrase"))
        return selector if selector is not None and selector.get("share") else None
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
