"""PLAY-ALL regressions for entry sequences and extra combat timing."""
import pytest

from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, filler, game, main_phase, step, stack_library


def _moraug_landfall(engine):
    land = filler(engine, "Land", type_line="Land")
    engine.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD,
        instance_id=land.instance_id, controller_id="p1", object_types=["land"]))
    engine.resolve_until_stable()


@pytest.mark.parametrize("main_step", ["main1", "main2"])
def test_moraug_untaps_only_when_its_extra_combat_trigger_resolves(main_step):
    engine = game()
    card(engine, "Moraug, Fury of Akoum")
    bear = filler(engine, "Bear", power=2, toughness=2)
    bear.tapped = True
    while engine.state.current_step != main_step:
        engine.advance_step()
    _moraug_landfall(engine)
    assert bear.tapped
    engine.interactive_priority = True
    engine.advance_step()
    assert engine.state.current_step == "begin_combat" and bear.tapped
    assert len(engine.state.stack) == 1
    # The delayed ability is respondable and survives its source leaving.
    moraug = next(o for o in engine.state.battlefield if o.name.startswith("Moraug"))
    engine.rules.destroy(moraug)
    engine.resolve_until_stable()
    assert not bear.tapped


def test_moraug_multiple_landfalls_each_untap_only_their_own_combat():
    engine = game()
    card(engine, "Moraug, Fury of Akoum")
    bear = filler(engine, "Bear", power=2, toughness=2)
    while engine.state.current_step != "main1":
        engine.advance_step()
    _moraug_landfall(engine)
    _moraug_landfall(engine)
    bear.tapped = True
    engine.advance_step()
    assert engine.state.current_step == "begin_combat" and not bear.tapped
    bear.tapped = True
    for _ in range(5):
        engine.advance_step()
    assert engine.state.current_step == "begin_combat" and not bear.tapped
    bear.tapped = True
    for _ in range(5):
        engine.advance_step()
    assert engine.state.current_step == "begin_combat" and bear.tapped


def test_inserted_combat_and_its_delayed_trigger_survive_state_restore():
    from mtg_analyzer.game.game_engine import GameEngine
    engine = game()
    card(engine, "Moraug, Fury of Akoum")
    while engine.state.current_step != "main1":
        engine.advance_step()
    _moraug_landfall(engine)
    engine.advance_step()
    cursor = engine.step_cursor
    restored = GameEngine(engine.state.clone())
    restored.resume_at(cursor)
    assert len(restored._turn_steps) == len(engine._turn_steps)
    assert sum(s.name == "begin_combat" for _, s in restored._turn_steps) == 2


def test_yarus_returns_face_down_then_turns_up_without_an_etb_trigger():
    engine = game()
    card(engine, "Yarus, Roar of the Old Gods")
    seer = card(engine, "Fathom Seer")
    engine.rules.turn_face_down(seer, "manifest")
    engine.rules.destroy(seer)
    before = len(engine.state.player_by_id("p1").hand)
    engine.resolve_until_stable()
    assert seer.zone == Zone.BATTLEFIELD and not seer.face_down
    assert len(engine.state.player_by_id("p1").hand) == before + 2
    entry = [e for e in engine.state.event_log if e.type == EventType.ENTERS_BATTLEFIELD
             and e.get("instance_id") == seer.instance_id][-1]
    assert entry.get("object") == "Face-down creature"


def test_yarus_does_not_return_a_manifested_instant():
    engine = game()
    card(engine, "Yarus, Roar of the Old Gods")
    bolt = card(engine, "Lightning Bolt")
    engine.rules.turn_face_down(bolt, "manifest")
    engine.rules.destroy(bolt)
    engine.resolve_until_stable()
    assert bolt.zone == Zone.GRAVEYARD


def test_yarus_return_does_not_fire_the_creatures_face_up_entry_ability():
    engine = game()
    card(engine, "Yarus, Roar of the Old Gods")
    visionary = card(engine, "Elvish Visionary")
    engine.rules.turn_face_down(visionary, "manifest")
    engine.rules.destroy(visionary)
    before = len(engine.state.player_by_id("p1").hand)
    engine.resolve_until_stable()
    assert visionary.zone == Zone.BATTLEFIELD and not visionary.face_down
    assert len(engine.state.player_by_id("p1").hand) == before


def test_yarus_does_not_return_a_card_that_left_and_reentered_the_graveyard():
    engine = game()
    card(engine, "Yarus, Roar of the Old Gods")
    seer = card(engine, "Fathom Seer")
    engine.rules.turn_face_down(seer, "manifest")
    engine.rules.destroy(seer)
    engine.rules.put_triggers_on_stack()
    engine.rules.exile(seer)
    seer.reset_as_new_object()
    me = engine.state.player_by_id("p1")
    me.remove_from_zone(seer, Zone.EXILE)
    me.add_to_zone(seer, Zone.GRAVEYARD)
    engine.resolve_until_stable()
    assert seer.zone == Zone.GRAVEYARD


@pytest.mark.parametrize("remove_source", [False, True])
def test_runadi_cast_trigger_can_be_countered_or_outlive_its_source(remove_source):
    engine = game()
    runadi = card(engine, "Runadi, Behemoth Caller")
    spell = filler(engine, "Large", mv=6, power=2, toughness=2, zone=Zone.HAND)
    me = engine.state.player_by_id("p1")
    me.mana_pool.add_many({"C": 6})
    main_phase(engine)
    engine.cast_spell(me, spell)
    engine.rules.put_triggers_on_stack()
    assert len(engine.state.stack) == 2
    if remove_source:
        engine.rules.destroy(runadi)
    else:
        engine.rules.counter_spell(engine.state.stack[-1])
    engine.resolve_until_stable()
    assert spell.counters.get("+1/+1", 0) == (2 if remove_source else 0)


def test_runadi_counts_announced_x_in_spell_mana_value():
    engine = game()
    card(engine, "Runadi, Behemoth Caller")
    spell = card(engine, "Walking Ballista", zone=Zone.HAND)
    me = engine.state.player_by_id("p1")
    me.mana_pool.add_many({"C": 6})
    main_phase(engine)
    engine.cast_spell(me, spell, x=3)
    engine.resolve_until_stable()
    assert spell.counters["+1/+1"] == 5  # three printed entry counters, plus 6−4


@pytest.mark.parametrize("pay_life", [False, True])
def test_turntimber_back_face_offers_entry_life_payment_and_green_mana(pay_life):
    engine = game()
    land = card(engine, "Turntimber Symbiosis", zone=Zone.HAND)
    me = engine.state.player_by_id("p1")
    main_phase(engine)
    engine.play_land(me, land, face="back")
    choice = engine.state.pending_choice
    assert choice is not None
    engine.resolve_pending_choice("pay" if pay_life else "decline")
    assert land.is_land and land.zone == Zone.BATTLEFIELD
    assert land.tapped is not pay_life and me.life == 20 - (3 if pay_life else 0)
    if pay_life:
        engine.tap_for_mana(me, land)
        assert me.mana_pool.pool["G"] == 1


@pytest.mark.parametrize("kind", ["Creature", "Planeswalker"])
def test_prismatic_bridge_back_face_reveals_and_puts_matching_card_into_play(kind):
    engine = game()
    bridge = card(engine, "Esika, God of the Tree", zone=Zone.HAND)
    me = engine.state.player_by_id("p1")
    me.mana_pool.add_many({"W": 1, "U": 1, "B": 1, "R": 1, "G": 1})
    main_phase(engine)
    engine.cast_spell(me, bridge, face="back")
    engine.resolve_until_stable()
    stats = {"power": 2, "toughness": 2} if kind == "Creature" else {"loyalty": 3}
    hit = filler(engine, "Hit", type_line=kind, zone=Zone.LIBRARY, **stats)
    miss = filler(engine, "Miss", type_line="Instant", zone=Zone.LIBRARY)
    stack_library(engine, "p1", hit, miss)
    step(engine, "upkeep")
    assert bridge.name == "The Prismatic Bridge" and hit.zone == Zone.BATTLEFIELD
    assert miss.zone == Zone.LIBRARY and me.library[0] is miss
    assert not any(e.type == EventType.EXILE and e.get("object") in {"Hit", "Miss"}
                   for e in engine.state.event_log)


def test_prismatic_bridge_resolves_the_creatures_entry_replacement_before_entry():
    engine = game()
    bridge = card(engine, "Esika, God of the Tree")
    engine.rules.switch_to_face(bridge, bridge.card.back_face())
    bear = filler(engine, "Bear", power=4, toughness=5)
    clone = card(engine, "Clone", zone=Zone.LIBRARY)
    stack_library(engine, "p1", clone)
    step(engine, "upkeep")
    assert engine.state.pending_choice["kind"] == "enter_as_copy"
    assert clone.zone == Zone.LIBRARY
    engine.resolve_pending_choice(str(bear.instance_id))
    engine.resolve_until_stable()
    assert clone.zone == Zone.BATTLEFIELD and clone.power == 4 and clone.toughness == 5


def test_moraug_does_not_trigger_on_a_land_outside_its_controllers_main_phase():
    engine = game()
    card(engine, "Moraug, Fury of Akoum")
    engine.state.current_step = "declare_attackers"
    land = filler(engine, "Land", type_line="Land")
    engine.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD,
        instance_id=land.instance_id, controller_id="p1", object_types=["land"]))
    engine.rules.put_triggers_on_stack()
    assert not engine.state.stack and not engine.state.pending_extra_combats
