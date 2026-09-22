"""Per-turn tallies derived from the turn-stamped event log (ENG-47).

"Life gained this turn", "spells cast this turn", "creatures that died this turn" used to be
a `GameState` counter each, bumped at one site and reset in `GameEngine.begin_turn` — a
second copy of what the fired events already say, with a reset scope that had to be chosen
per counter (and was, wrongly, only the incoming player's for several). Here each one is a
pure function over the current turn's events, so there is nothing to bump and nothing to
reset: a new turn has a new window.

Every function takes ``events`` (any iterable of `GameEvent`, the current turn's) and
returns a fresh ``defaultdict`` so a reader may use ``.get(pid, 0)`` or ``[pid]`` alike. The
payload each one reads is stamped by the event's own fire site.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable, Iterable, Optional

from .events import EventType, GameEvent

Events = Iterable[GameEvent]


def _tally(
    events: Events,
    event_type: str,
    key: str,
    *,
    weight: Optional[str] = None,
    where: Optional[Callable[[GameEvent], bool]] = None,
) -> "defaultdict[Any, int]":
    """``{event[key]: sum of event[weight] (or the count of events)}`` over one event type."""
    out: "defaultdict[Any, int]" = defaultdict(int)
    for event in events:
        if event.type != event_type:
            continue
        who = event.get(key)
        if who is None or (where is not None and not where(event)):
            continue
        out[who] += int(event.get(weight) or 0) if weight else 1
    return out


def life_gained(events: Events) -> "defaultdict[str, int]":
    return _tally(events, EventType.LIFE_GAINED, "player_id", weight="amount")


def life_lost(events: Events) -> "defaultdict[str, int]":
    return _tally(events, EventType.LIFE_LOST, "player_id", weight="amount")


def cards_discarded(events: Events) -> "defaultdict[str, int]":
    return _tally(events, EventType.DISCARD_CARD, "player_id")


def cards_drawn(events: Events) -> "defaultdict[str, int]":
    return _tally(events, EventType.DRAW, "player_id", weight="count")


def cards_drawn_ids(events: Events) -> "defaultdict[str, list[int]]":
    """The specific objects each player drew this turn, oldest first (the log is newest
    first, so the events are reversed here)."""
    out: "defaultdict[str, list[int]]" = defaultdict(list)
    for event in reversed(list(events)):
        if event.type == EventType.DRAW and event.get("player_id") is not None:
            out[event.get("player_id")].extend(event.get("instance_ids") or [])
    return out


# -- spells cast (SPELL_CAST carries object_types, mana_value, colors, subtypes, has_x) ----


def _casts(events: Events) -> "list[GameEvent]":
    return [e for e in events if e.type == EventType.SPELL_CAST and e.get("player_id") is not None]


def _is_instant_or_sorcery(event: GameEvent) -> bool:
    types = event.get("object_types") or []
    return "instant" in types or "sorcery" in types


def spells_cast(events: Events) -> "defaultdict[str, int]":
    return _tally(events, EventType.SPELL_CAST, "player_id")


def noncreature_spells_cast(events: Events) -> "defaultdict[str, int]":
    return _tally(events, EventType.SPELL_CAST, "player_id",
                  where=lambda e: "creature" not in (e.get("object_types") or []))


def nonartifact_spells_cast(events: Events) -> "defaultdict[str, int]":
    return _tally(events, EventType.SPELL_CAST, "player_id",
                  where=lambda e: "artifact" not in (e.get("object_types") or []))


def cast_instant_or_sorcery(events: Events) -> "defaultdict[str, bool]":
    out: "defaultdict[str, bool]" = defaultdict(bool)
    for event in _casts(events):
        if _is_instant_or_sorcery(event):
            out[event.get("player_id")] = True
    return out


def greatest_instant_sorcery_mv(events: Events) -> "defaultdict[str, int]":
    out: "defaultdict[str, int]" = defaultdict(int)
    for event in _casts(events):
        if _is_instant_or_sorcery(event):
            who = event.get("player_id")
            out[who] = max(out[who], int(event.get("mana_value") or 0))
    return out


def spell_colors_cast(events: Events) -> "defaultdict[str, set[str]]":
    out: "defaultdict[str, set[str]]" = defaultdict(set)
    for event in _casts(events):
        out[event.get("player_id")].update(event.get("colors") or [])
    return out


def spell_color_cast_counts(events: Events) -> "defaultdict[str, dict[str, int]]":
    out: "defaultdict[str, dict[str, int]]" = defaultdict(dict)
    for event in _casts(events):
        counts = out[event.get("player_id")]
        for color in event.get("colors") or []:
            counts[color] = counts.get(color, 0) + 1
    return out


def spell_type_cast_counts(events: Events) -> "defaultdict[str, dict[str, int]]":
    out: "defaultdict[str, dict[str, int]]" = defaultdict(dict)
    for event in _casts(events):
        counts = out[event.get("player_id")]
        for card_type in event.get("object_types") or []:
            counts[card_type] = counts.get(card_type, 0) + 1
        if _is_instant_or_sorcery(event):
            counts["instant_or_sorcery"] = counts.get("instant_or_sorcery", 0) + 1
    return out


def creature_type_spells_cast(events: Events) -> "defaultdict[str, set[str]]":
    """The subtypes of the spells each player cast (creature types, but any subtype word)."""
    out: "defaultdict[str, set[str]]" = defaultdict(set)
    for event in _casts(events):
        out[event.get("player_id")].update(event.get("subtypes") or [])
    return out


def cast_x_spell(events: Events) -> "set[str]":
    """Players who cast a spell with {X} in its mana cost."""
    return {e.get("player_id") for e in _casts(events) if e.get("has_x")}


# -- creatures that died (DIES carries object_types, controller_id, counters) ---------------


def creatures_died(events: Events) -> "defaultdict[str, int]":
    return _tally(events, EventType.DIES, "controller_id",
                  where=lambda e: "creature" in (e.get("object_types") or []))


def modified_creatures_died(events: Events) -> "defaultdict[str, int]":
    """Documented simplification (Intermediate Chirography): "modified" means it had one or
    more counters, read off the DIES event's snapshotted ``counters`` (RULE 400.7)."""
    return _tally(
        events, EventType.DIES, "controller_id",
        where=lambda e: "creature" in (e.get("object_types") or [])
        and any(int(v) > 0 for v in (e.get("counters") or {}).values()),
    )


# -- damage (DAMAGE carries is_player, target_id, source_id, source_controller_id, combat) --


def damage_dealt_to_players(events: Events) -> "defaultdict[str, int]":
    return _tally(events, EventType.DAMAGE, "target_id", weight="amount",
                  where=lambda e: bool(e.get("is_player")))


def damage_dealt_by(events: Events) -> "defaultdict[str, int]":
    """Damage dealt to players, summed per dealing source's controller."""
    return _tally(events, EventType.DAMAGE, "source_controller_id", weight="amount",
                  where=lambda e: bool(e.get("is_player")) and e.get("source_id") is not None)


def combat_damage_to_players(events: Events) -> "defaultdict[int, set[str]]":
    """``{source instance id: the players it dealt combat damage to}``."""
    out: "defaultdict[int, set[str]]" = defaultdict(set)
    for event in events:
        if (event.type == EventType.DAMAGE and event.get("is_player") and event.get("combat")
                and event.get("source_id") is not None):
            out[event.get("source_id")].add(event.get("target_id"))
    return out


def noncombat_damage_to_opponents(events: Events) -> "defaultdict[str, int]":
    return _tally(
        events, EventType.DAMAGE, "source_controller_id", weight="amount",
        where=lambda e: bool(e.get("is_player")) and not e.get("combat")
        and e.get("source_id") is not None
        and e.get("source_controller_id") != e.get("target_id"),
    )


def creatures_damaged_by_source(events: Events) -> "defaultdict[int, set[int]]":
    """``{creature instance id: the sources that damaged it}`` (any damage, combat or not)."""
    out: "defaultdict[int, set[int]]" = defaultdict(set)
    for event in events:
        if (event.type == EventType.DAMAGE and event.get("target_is_creature")
                and event.get("source_id") is not None):
            out[event.get("target_id")].add(event.get("source_id"))
    return out


# -- cards that reached a graveyard, bends, counters ------------------------------------------

_PERMANENT_CARD_TYPES = frozenset({"artifact", "battle", "creature", "enchantment", "land", "planeswalker"})


def _graveyard_arrivals(events: Events) -> "Iterable[tuple[str, list[str]]]":
    """``(owner id, card types)`` for every card that went to a graveyard this turn from the
    battlefield (DIES), the hand (DISCARD_CARD) or the library (MILLED_CARD) — each event
    snapshots the card's types, since the card is no longer where it was (RULE 400.7). A
    token is not a card, so its DIES event does not count."""
    for event in events:
        if event.type == EventType.DIES:
            if event.get("is_token"):
                continue  # a token ceases to exist (RULE 111.7); no card reached the graveyard
            owner = event.get("owner_id")
        elif event.type == EventType.DISCARD_CARD:
            owner = event.get("player_id")
        elif event.type == EventType.MILLED_CARD:
            owner = event.get("owner_id") or event.get("player_id")
        else:
            continue
        if owner is not None:
            yield owner, list(event.get("object_types") or [])


def creature_card_to_graveyard(events: Events) -> "set[str]":
    """Owners into whose graveyard a creature card went from anywhere (Cloakwood Hermit)."""
    return {owner for owner, types in _graveyard_arrivals(events) if "creature" in types}


def permanent_card_to_graveyard(events: Events) -> "set[str]":
    """Owners into whose graveyard a permanent card went from anywhere (RULE 702.175)."""
    return {owner for owner, types in _graveyard_arrivals(events) if _PERMANENT_CARD_TYPES & set(types)}


def bends(events: Events) -> "defaultdict[str, set[str]]":
    """The bending keyword actions each player performed (RULE 701.6x)."""
    out: "defaultdict[str, set[str]]" = defaultdict(set)
    for event in events:
        if event.type == EventType.BENT and event.get("player_id") is not None and event.get("kind"):
            out[event.get("player_id")].add(event.get("kind"))
    return out


def counter_placed_on_creature(events: Events) -> "set[str]":
    """Controllers of the sources that put a counter on a creature this turn (Lasting
    Tarfire) — the COUNTER event carries the causer and whether the recipient is a creature."""
    return {
        event.get("source_controller_id") for event in events
        if event.type == EventType.COUNTER and event.get("recipient_is_creature")
        and (event.get("amount") or 0) > 0 and event.get("source_controller_id") is not None
    }


# -- permanents entering and leaving the battlefield ---------------------------------------------


def nontoken_creatures_entered(events: Events) -> "defaultdict[str, int]":
    """Nontoken creatures that entered under each player's control (Gyome, Master Chef)."""
    return _tally(events, EventType.ENTERS_BATTLEFIELD, "controller_id",
                  where=lambda e: "creature" in (e.get("object_types") or []) and not e.get("is_token"))


def lands_entered(events: Events) -> "defaultdict[str, int]":
    """Lands that entered under each player's control (Zimone, All-Questioning)."""
    return _tally(events, EventType.ENTERS_BATTLEFIELD, "controller_id",
                  where=lambda e: "land" in (e.get("object_types") or []))


def permanents_left_battlefield(events: Events) -> "defaultdict[str, int]":
    """Permanents that left the battlefield, per controller (Revolt / Disappear, MEC-84)."""
    return _tally(events, EventType.LEAVES_BATTLEFIELD, "controller_id")


def creatures_left_battlefield(events: Events) -> "defaultdict[str, int]":
    return _tally(events, EventType.LEAVES_BATTLEFIELD, "controller_id",
                  where=lambda e: "creature" in (e.get("object_types") or []))


def players_attacked(events: Events) -> "set[str]":
    """Players who declared an attacker this turn (RULE 508.1a; Raid)."""
    return {e.get("player_id") for e in events
            if e.type == EventType.ATTACKS and e.get("declared") and e.get("player_id") is not None}


def combats(events: Events) -> int:
    """Combat phases this turn, game-wide (RULE 603.4 — "if it's the first combat phase of
    the turn"): one per ``begin_combat`` step that actually began, so an extra combat phase is
    the second whoever controls the effect that grants it."""
    return sum(1 for e in events if e.type == EventType.STEP_BEGIN and e.get("step") == "begin_combat")


def planar_die_rolls(events: Events) -> "defaultdict[str, int]":
    """Times each player rolled the planar die this turn (RULE 901.6b)."""
    return _tally(events, EventType.PLANAR_DIE_ROLLED, "player_id")
