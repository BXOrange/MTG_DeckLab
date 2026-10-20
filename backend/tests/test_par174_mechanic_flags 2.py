"""PAR-174: the six per-mechanic `AbilitySpec` flags are gone; the cards that used
them are ordinary specs over registered effects.

Behaviour of the migrated cards is pinned by their own suites
(`test_rad_counters.py`, `test_rad_counter_deferred_gaps.py`,
`test_mill_trigger_family.py`, `test_counter_death_return_variants.py`,
`test_ragavan_and_mnemonic_betrayal.py`, `test_mec_12_cedh_batch_6.py`); this file
covers what the migration newly relies on.
"""

from __future__ import annotations

import dataclasses

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import GameState
from mtg_analyzer.models.game.player import Player
from mtg_analyzer.parser.oracle.spec import AbilitySpec

RETIRED_FIELDS = (
    "rad_counters_on_combat_damage",
    "rad_counters_on_attacked",
    "mill_return_from_graveyard",
    "enter_or_graveyard_discard_land",
    "impulsive_draw_on_combat_damage",
    "counter_death_return",
)


def _engine():
    state = GameState(players=[Player(id="p1", name="Alice", life=20), Player(id="p2", name="Bob", life=20)])
    return GameEngine(state), state


def _to_hand(engine, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.HAND)
    bind_from_catalogue(obj)
    engine.state.player_by_id(controller).hand.append(obj)
    return obj


def _land(name):
    return Card(id=name, name=name, type_line="Basic Land", is_land=True)


MOX = Card(
    id="mox", name="Mox Diamond", type_line="Artifact", mana_cost_string="{0}", converted_mana_cost=0,
    oracle_text="If Mox Diamond would enter, you may discard a land card instead. If you do, put "
                "Mox Diamond onto the battlefield. If you don't, put it into its owner's graveyard.",
)


def _cast_mox(engine, state):
    engine.begin_turn()
    while engine.state.active_player.id != "p1":
        engine.begin_turn()
    state.current_step = "main1"
    spell = _to_hand(engine, MOX)
    return spell


def test_the_six_mechanic_flags_are_retired():
    fields = {f.name for f in dataclasses.fields(AbilitySpec)}
    assert not fields & set(RETIRED_FIELDS)
    obj = GameObject(_land("Forest"), owner_id="p1", zone=Zone.HAND)
    assert not any(hasattr(obj, name) for name in RETIRED_FIELDS)


def test_mox_diamond_offers_only_lands_and_discards_the_chosen_one():
    engine, state = _engine()
    p1 = state.player_by_id("p1")
    mox = _cast_mox(engine, state)
    forest = _to_hand(engine, _land("Forest"))
    island = _to_hand(engine, _land("Island"))
    bear = _to_hand(engine, Card(id="bear", name="Bear", type_line="Creature — Bear", is_creature=True))
    discards = []
    state.subscribe(lambda e: discards.append(e.get("instance_id")) if e.type == EventType.DISCARD_CARD else None)

    engine.cast_spell(p1, mox, targets=None)
    engine.resolve_until_stable()
    assert state.pending_choice["kind"] == "pay_cost_then"
    engine.rules.resolve_choice("pay")

    pick = state.pending_choice
    assert pick["action"] == "discard"
    assert {o["instance_id"] for o in pick["options"]} == {forest.instance_id, island.instance_id}
    engine.rules.resolve_choice(str(island.instance_id))
    engine.resolve_until_stable()

    assert mox in state.battlefield
    assert island in p1.graveyard and forest in p1.hand and bear in p1.hand
    assert discards == [island.instance_id]


def test_mox_diamond_with_only_a_nonland_in_hand_goes_straight_to_the_graveyard():
    engine, state = _engine()
    p1 = state.player_by_id("p1")
    mox = _cast_mox(engine, state)
    _to_hand(engine, Card(id="bear", name="Bear", type_line="Creature — Bear", is_creature=True))

    engine.cast_spell(p1, mox, targets=None)
    engine.resolve_until_stable()

    assert state.pending_choice is None
    assert mox in p1.graveyard and mox not in state.battlefield


def test_a_filtered_discard_cost_is_not_payable_without_a_matching_card():
    from mtg_analyzer.game.costs import parse_activation_cost

    engine, state = _engine()
    p1 = state.player_by_id("p1")
    _to_hand(engine, Card(id="bear", name="Bear", type_line="Creature — Bear", is_creature=True))
    cost = parse_activation_cost("Discard a land card")
    assert not engine.rules._can_pay_player_cost(p1, cost, None)
    _to_hand(engine, _land("Forest"))
    assert engine.rules._can_pay_player_cost(p1, cost, None)


def test_infesting_radroach_does_not_fire_from_the_battlefield_on_an_opponents_mill():
    engine, state = _engine()
    roach = GameObject(
        Card(id="roach", name="Infesting Radroach", type_line="Creature — Insect Mutant", is_creature=True,
             power=3, toughness=1),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    bind_from_catalogue(roach)
    state.add_to_battlefield(roach)
    p2 = state.player_by_id("p2")
    p2.library.append(GameObject(
        Card(id="c", name="Filler", type_line="Creature — Bear", is_creature=True), owner_id="p2", zone=Zone.LIBRARY,
    ))
    engine.rules.mill(p2, 1)
    assert engine.rules.put_triggers_on_stack() == 0


def test_struggle_for_project_purity_enclave_does_not_fire_for_its_own_controllers_attack():
    engine, state = _engine()
    struggle = GameObject(
        Card(id="sfpp", name="Struggle for Project Purity", type_line="Enchantment"),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    bind_from_catalogue(struggle)
    struggle.chosen_mode = "enclave"
    state.add_to_battlefield(struggle)
    # p1 (the Struggle's controller) attacks p2: "attacks *you*" is false.
    state.fire_event(GameEvent(
        EventType.PLAYER_ATTACKED, attacking_player_id="p1", defending_player_id="p2", count=2,
    ))
    assert engine.rules.put_triggers_on_stack() == 0


# ---------------------------------------------------------------------------
# Mox Diamond entering through a battlefield batch (RULE 614.12 applies to every entry)
# ---------------------------------------------------------------------------


def _mox_in_graveyard(engine, state):
    mox = GameObject(MOX, owner_id="p1", zone=Zone.GRAVEYARD)
    bind_from_catalogue(mox)
    state.player_by_id("p1").graveyard.append(mox)
    return mox


def _bear_in_graveyard(state):
    bear = GameObject(
        Card(id="bear", name="Bear", type_line="Creature — Bear", is_creature=True, power=2, toughness=2),
        owner_id="p1", zone=Zone.GRAVEYARD,
    )
    bind_from_catalogue(bear)
    state.player_by_id("p1").graveyard.append(bear)
    return bear


def _watch_entries(state):
    entered = []
    state.subscribe(lambda e: entered.append(e.get("instance_id")) if e.type == EventType.ENTERS_BATTLEFIELD else None)
    return entered


def _return_batch(engine, state, *objs):
    from mtg_analyzer.game.effects.battlefield_batches import start_zone_return_batch

    start_zone_return_batch(engine.rules, [(o.instance_id, o.zone_incarnation) for o in objs], "graveyard", "p1")


def test_reanimated_mox_diamond_pays_a_land_and_enters():
    engine, state = _engine()
    p1 = state.player_by_id("p1")
    mox = _mox_in_graveyard(engine, state)
    forest = _to_hand(engine, _land("Forest"))
    entered = _watch_entries(state)
    _return_batch(engine, state, mox)
    assert state.pending_choice["kind"] == "pay_cost_then"
    engine.rules.resolve_choice("pay")
    engine.resolve_until_stable()
    assert mox in state.battlefield and entered == [mox.instance_id]
    assert forest in p1.graveyard


def test_reanimated_mox_diamond_declined_never_enters():
    engine, state = _engine()
    p1 = state.player_by_id("p1")
    mox = _mox_in_graveyard(engine, state)
    _to_hand(engine, _land("Forest"))
    entered = _watch_entries(state)
    _return_batch(engine, state, mox)
    engine.rules.resolve_choice("decline")
    engine.resolve_until_stable()
    assert mox in p1.graveyard and mox not in state.battlefield and entered == []


def test_reanimated_mox_diamond_without_a_land_never_enters():
    engine, state = _engine()
    p1 = state.player_by_id("p1")
    mox = _mox_in_graveyard(engine, state)
    entered = _watch_entries(state)
    _return_batch(engine, state, mox)
    assert state.pending_choice is None
    assert mox in p1.graveyard and entered == []


def test_only_mox_fails_in_a_two_object_batch():
    engine, state = _engine()
    p1 = state.player_by_id("p1")
    mox = _mox_in_graveyard(engine, state)
    bear = _bear_in_graveyard(state)
    _to_hand(engine, _land("Forest"))
    entered = _watch_entries(state)
    _return_batch(engine, state, mox, bear)
    engine.rules.resolve_choice("decline")
    engine.resolve_until_stable()
    assert bear in state.battlefield and mox in p1.graveyard
    assert entered == [bear.instance_id]


def test_mox_batch_choice_survives_a_state_clone():
    engine, state = _engine()
    mox = _mox_in_graveyard(engine, state)
    _to_hand(engine, _land("Forest"))
    _return_batch(engine, state, mox)
    clone = state.clone()
    assert clone.pending_choice["kind"] == "pay_cost_then"
    assert clone.pending_choice["battlefield_batch"]["cursor"] == 0


def test_mox_diamond_asks_again_on_every_new_entry():
    engine, state = _engine()
    mox = _mox_in_graveyard(engine, state)
    lands = [_to_hand(engine, _land(n)) for n in ("F", "G", "H")]
    _return_batch(engine, state, mox)
    engine.rules.resolve_choice("pay")
    engine.rules.resolve_choice(str(lands[0].instance_id))
    engine.resolve_until_stable()
    assert mox in state.battlefield
    engine.rules.destroy(mox)
    engine.resolve_until_stable()
    _return_batch(engine, state, mox)
    assert state.pending_choice["kind"] == "pay_cost_then"
