"""Tests for the "whenever a player/an opponent mills a nonland card"/
"whenever one or more nonland cards are milled" trigger family — the
"Library-top / impulsive-draw permissions"-adjacent gap `backend/
BACKLOG.md`'s former "Rad counters (RULE 728)" entry left open (now
closed): the two named sub-gaps were "goaded" (moved to the Multiplayer
ToDo entry, unrelated to this file) and this mill-trigger family.

Covers the new generic engine primitive — `EventType.MILL_CARD`
(`RulesEngine.mill`, fired once per *nonland* card, never a land) plus its
`effect_binder` "group" subject controller scoping (mirroring
`LIBRARY_SEARCHED`'s existing "an opponent searches" shape) — and all three
real cards it unblocks: Glowing One (any player, gain life), Infesting
Radroach (an opponent, RULE 112.6a graveyard-functioning return-to-hand via
the new `AbilitySpec.mill_return_from_graveyard` marker), and The Wise
Mothman (per-nonland-card "up to one target creature" decomposition of its
printed aggregate "up to X targets" wording — see `_the_wise_mothman`'s own
docstring in `game/ability_catalogue.py` for why that's rules-equivalent).
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def _creature(name, power=2, toughness=2, type_line="Creature — Bear", **kw):
    return Card(id=name, name=name, type_line=type_line, is_creature=True,
                power=power, toughness=toughness, **kw)


def _land(name="Island"):
    return Card(id=name, name=name, type_line="Basic Land — Island", is_land=True)


def _put(state, card, controller="p1", zone=Zone.BATTLEFIELD):
    obj = GameObject(card, owner_id=controller, zone=zone)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    if zone == Zone.BATTLEFIELD:
        state.add_to_battlefield(obj)
    else:
        state.player_by_id(controller).add_to_zone(obj, zone)
    return obj


def _glowing_one_card():
    return Card(id="Glowing One", name="Glowing One", type_line="Creature — Mutant",
                is_creature=True, power=1, toughness=1, keywords=["Deathtouch"])


def _radroach_card():
    return Card(id="Infesting Radroach", name="Infesting Radroach",
                type_line="Creature — Insect Mutant", is_creature=True, power=1, toughness=1,
                keywords=["Flying"])


def _mothman_card():
    return Card(id="The Wise Mothman", name="The Wise Mothman",
                type_line="Legendary Creature — Insect Mutant", is_creature=True,
                power=3, toughness=3, keywords=["Flying"])


# ---------------------------------------------------------------------------
# The generic primitive: EventType.MILL_CARD.
# ---------------------------------------------------------------------------


def test_mill_fires_mill_card_once_per_nonland_card_only():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    p1.library.append(GameObject(_creature("Nonland1"), owner_id="p1", zone=Zone.LIBRARY))
    p1.library.append(GameObject(_land(), owner_id="p1", zone=Zone.LIBRARY))
    p1.library.append(GameObject(_creature("Nonland2"), owner_id="p1", zone=Zone.LIBRARY))

    seen: list[GameEvent] = []
    eng.state.subscribe(lambda e: seen.append(e) if e.type == EventType.MILL_CARD else None)
    eng.rules.mill(p1, 3)

    assert len(seen) == 2  # the land is skipped
    assert all(e.get("player_id") == "p1" for e in seen)


def test_mill_still_fires_the_aggregate_mill_event_unchanged():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    p1.library.append(GameObject(_land(), owner_id="p1", zone=Zone.LIBRARY))

    seen: list[GameEvent] = []
    eng.state.subscribe(lambda e: seen.append(e) if e.type == EventType.MILL else None)
    eng.rules.mill(p1, 1)

    assert len(seen) == 1
    assert seen[0].get("count") == 1


# ---------------------------------------------------------------------------
# Glowing One — any player's nonland mill, gain 1 life. Plain group-subject
# triggered ability, no card-varying marker needed.
# ---------------------------------------------------------------------------


def test_glowing_one_gains_life_when_an_opponent_mills_a_nonland_card():
    eng = _engine()
    _put(eng.state, _glowing_one_card(), controller="p1")
    p1 = eng.state.player_by_id("p1")
    p2 = eng.state.player_by_id("p2")
    p2.library.append(GameObject(_creature("Fodder"), owner_id="p2", zone=Zone.LIBRARY))

    eng.rules.mill(p2, 1)
    placed = eng.rules.put_triggers_on_stack()
    assert placed == 1
    eng.rules.resolve_top_of_stack()

    assert p1.life == 21


def test_glowing_one_also_gains_life_on_its_own_controllers_mill():
    eng = _engine()
    _put(eng.state, _glowing_one_card(), controller="p1")
    p1 = eng.state.player_by_id("p1")
    p1.library.append(GameObject(_creature("Fodder"), owner_id="p1", zone=Zone.LIBRARY))

    eng.rules.mill(p1, 1)
    assert eng.rules.put_triggers_on_stack() == 1
    eng.rules.resolve_top_of_stack()

    assert p1.life == 21


def test_glowing_one_does_not_trigger_on_a_land_mill():
    eng = _engine()
    _put(eng.state, _glowing_one_card(), controller="p1")
    p2 = eng.state.player_by_id("p2")
    p2.library.append(GameObject(_land(), owner_id="p2", zone=Zone.LIBRARY))

    eng.rules.mill(p2, 1)
    assert eng.rules.put_triggers_on_stack() == 0


# ---------------------------------------------------------------------------
# Infesting Radroach — RULE 112.6a graveyard-functioning ability: only an
# *opponent's* mill triggers it, and only while it's actually sitting in its
# controller's graveyard.
# ---------------------------------------------------------------------------


def _radroach_in_graveyard(eng):
    radroach = _put(eng.state, _radroach_card(), controller="p1")
    eng.rules.destroy(radroach)
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_top_of_stack()
    assert radroach.zone == Zone.GRAVEYARD
    return radroach


def test_radroach_does_not_trigger_on_its_own_controllers_mill():
    eng = _engine()
    _radroach_in_graveyard(eng)
    p1 = eng.state.player_by_id("p1")
    p1.library.append(GameObject(_creature("Filler"), owner_id="p1", zone=Zone.LIBRARY))

    eng.rules.mill(p1, 1)
    assert eng.rules.put_triggers_on_stack() == 0


def test_radroach_triggers_on_an_opponents_mill_and_may_return_to_hand():
    eng = _engine()
    radroach = _radroach_in_graveyard(eng)
    p1 = eng.state.player_by_id("p1")
    p2 = eng.state.player_by_id("p2")
    p2.library.append(GameObject(_creature("Filler"), owner_id="p2", zone=Zone.LIBRARY))

    eng.rules.mill(p2, 1)
    placed = eng.rules.put_triggers_on_stack()
    assert placed == 1
    choice = eng.state.pending_choice
    assert choice["kind"] == "trigger_target"

    eng.rules.resolve_choice("do")
    eng.resolve_until_stable()

    assert radroach.zone == Zone.HAND
    assert radroach in p1.hand


def test_radroach_may_decline_and_stays_in_the_graveyard():
    eng = _engine()
    radroach = _radroach_in_graveyard(eng)
    p2 = eng.state.player_by_id("p2")
    p2.library.append(GameObject(_creature("Filler"), owner_id="p2", zone=Zone.LIBRARY))

    eng.rules.mill(p2, 1)
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_choice("decline")
    eng.resolve_until_stable()

    assert radroach.zone == Zone.GRAVEYARD


def test_radroach_does_not_trigger_on_a_land_mill():
    eng = _engine()
    _radroach_in_graveyard(eng)
    p2 = eng.state.player_by_id("p2")
    p2.library.append(GameObject(_land(), owner_id="p2", zone=Zone.LIBRARY))

    eng.rules.mill(p2, 1)
    assert eng.rules.put_triggers_on_stack() == 0


def test_radroach_on_the_battlefield_does_not_spuriously_trigger():
    # Still alive — never entered a graveyard, so the graveyard-scan
    # collector has nothing to find for it.
    eng = _engine()
    _put(eng.state, _radroach_card(), controller="p1")
    p2 = eng.state.player_by_id("p2")
    p2.library.append(GameObject(_creature("Filler"), owner_id="p2", zone=Zone.LIBRARY))

    eng.rules.mill(p2, 1)
    assert eng.rules.put_triggers_on_stack() == 0


# ---------------------------------------------------------------------------
# The Wise Mothman — both abilities (registering the card bypasses the
# oracle-text parser wholesale, so the already-working "enters or attacks"
# rad-counter trigger is reproduced by hand too, verified below).
# ---------------------------------------------------------------------------


def test_mothman_enters_or_attacks_still_grants_rad_counters_once_registered():
    eng = _engine()
    moth = _put(eng.state, _mothman_card(), controller="p1", zone=Zone.HAND)
    eng.state.add_to_battlefield(moth)
    eng.state.fire_event(GameEvent(
        EventType.ENTERS_BATTLEFIELD, controller_id="p1", instance_id=moth.instance_id,
        object_types=sorted(moth.type_words),
    ))
    assert eng.rules.put_triggers_on_stack() == 1
    eng.rules.resolve_top_of_stack()

    assert eng.state.player_by_id("p1").counters.get("rad", 0) == 1
    assert eng.state.player_by_id("p2").counters.get("rad", 0) == 1


def test_mothman_places_one_counter_trigger_per_nonland_card_milled():
    eng = _engine()
    _put(eng.state, _mothman_card(), controller="p1")
    bear1 = _put(eng.state, _creature("Bear1"), controller="p1")
    bear2 = _put(eng.state, _creature("Bear2"), controller="p1")
    p2 = eng.state.player_by_id("p2")
    p2.library.append(GameObject(_creature("NL1"), owner_id="p2", zone=Zone.LIBRARY))
    p2.library.append(GameObject(_land(), owner_id="p2", zone=Zone.LIBRARY))
    p2.library.append(GameObject(_creature("NL2"), owner_id="p2", zone=Zone.LIBRARY))

    eng.rules.mill(p2, 3)  # 2 nonland + 1 land
    placed = eng.rules.put_triggers_on_stack()
    assert placed == 2  # once per nonland card, never for the land

    choice = eng.state.pending_choice
    assert choice["kind"] == "trigger_target"
    bear1_opt = next(o for o in choice["options"] if o.get("instance_id") == bear1.instance_id)
    eng.rules.resolve_choice(bear1_opt["id"])

    choice = eng.state.pending_choice
    assert any(o["id"] == "decline" for o in choice["options"])  # "up to one" is skippable
    eng.rules.resolve_choice("decline")
    eng.resolve_until_stable()

    assert bear1.counters.get("+1/+1", 0) == 1
    assert bear2.counters.get("+1/+1", 0) == 0


def test_mothman_does_not_trigger_on_a_pure_land_mill():
    eng = _engine()
    _put(eng.state, _mothman_card(), controller="p1")
    p2 = eng.state.player_by_id("p2")
    p2.library.append(GameObject(_land(), owner_id="p2", zone=Zone.LIBRARY))

    eng.rules.mill(p2, 1)
    assert eng.rules.put_triggers_on_stack() == 0
