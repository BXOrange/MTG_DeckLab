"""RULE 701.66: object-bound delayed returns, independent of turn and source."""
import pytest

from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import game, card, filler, cast, answer, pick_label, main_phase


@pytest.mark.parametrize("leave", ["destroy", "exile"])
def test_earthbent_land_returns_tapped_without_animation_or_old_counters(leave):
    engine = game()
    land = filler(engine, "Our land", type_line="Land")
    engine.rules.earthbend(land, 4)
    assert land.is_creature and land.power == 4
    getattr(engine.rules, leave)(land)
    assert land.zone != Zone.BATTLEFIELD
    engine.rules.put_triggers_on_stack()
    assert engine.state.stack
    engine.resolve_until_stable()
    assert land.zone == Zone.BATTLEFIELD and land.tapped
    assert not land.is_creature and land.counters.get("+1/+1", 0) == 0


def test_earthbend_return_persists_across_turns_and_source_control_changes():
    engine = game()
    source = filler(engine, "Bender", power=1, toughness=1)
    land = filler(engine, "Borrowed land", type_line="Land", player="p2")
    land.controller_id = "p1"
    engine.rules.earthbend(land, 4, source=source)
    engine.begin_turn()
    source.controller_id = "p2"
    engine.rules.destroy(land)
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()
    assert land.zone == Zone.BATTLEFIELD and land.controller_id == "p1" and land.tapped


def test_bounced_land_does_not_keep_the_animation_or_the_delayed_return():
    engine = game()
    land = filler(engine, "Land", type_line="Land")
    engine.rules.earthbend(land, 4)
    engine.rules.return_to_hand(land)
    main_phase(engine)
    engine.play_land(engine.state.player_by_id("p1"), land)
    engine.resolve_until_stable()
    assert not land.is_creature
    engine.rules.exile(land)
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()
    assert land.zone == Zone.EXILE


def test_return_countered_then_exile_does_not_trigger_again():
    engine = game()
    land = filler(engine, "Land", type_line="Land")
    bender = filler(engine, "Bender", power=1, toughness=1)
    engine.rules.earthbend(land, 4, source=bender)
    engine.rules.destroy(land)
    engine.rules.put_triggers_on_stack()
    returning = engine.state.stack[-1]
    stifle = card(engine, "Stifle", zone=Zone.HAND)
    cast(engine, stifle, targets=[returning])
    engine.rules.exile(land)
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()
    assert land.zone == Zone.EXILE


def test_a_new_graveyard_incarnation_cannot_be_returned_by_the_old_trigger():
    engine = game()
    land = filler(engine, "Land", type_line="Land")
    engine.rules.earthbend(land, 4)
    engine.rules.destroy(land)
    engine.rules.put_triggers_on_stack()
    engine.rules.exile(land)
    engine.rules.return_to_hand(land)
    engine.rules.discard(engine.state.player_by_id("p1"), 1)
    engine.resolve_until_stable()
    assert land.zone == Zone.GRAVEYARD


def test_delayed_return_and_animation_binding_survive_a_state_clone():
    from mtg_analyzer.game.game_engine import GameEngine

    engine = game()
    land = filler(engine, "Land", type_line="Land")
    bender = filler(engine, "Bender", power=1, toughness=1)
    engine.rules.earthbend(land, 4, source=bender)
    clone = GameEngine(engine.state.clone())
    copied_land = clone.state.find_object(land.instance_id)
    clone.rules.exile(copied_land)
    clone.rules.put_triggers_on_stack()
    clone.resolve_until_stable()
    assert copied_land.zone == Zone.BATTLEFIELD and copied_land.tapped and not copied_land.is_creature
    assert land.zone == Zone.BATTLEFIELD and land.is_creature and not land.tapped


def test_earthbend_zero_still_installs_the_return_before_state_based_death():
    engine = game()
    land = filler(engine, "Land", type_line="Land")
    engine.rules.earthbend(land, 0)
    assert land.zone == Zone.GRAVEYARD
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()
    assert land.zone == Zone.BATTLEFIELD and land.tapped and not land.is_creature


def test_a_departed_bender_cannot_return_another_players_land():
    engine = game(players=3)
    bender = filler(engine, "Bender", power=1, toughness=1)
    land = filler(engine, "Borrowed land", type_line="Land", player="p2")
    land.controller_id = "p1"
    engine.rules.earthbend(land, 4, source=bender)
    engine.rules.concede(engine.state.player_by_id("p1"))
    engine.rules.destroy(land)
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()
    assert land.zone == Zone.GRAVEYARD


def test_fatal_fissure_announces_the_land_only_when_its_death_trigger_fires():
    engine = game()
    spell = card(engine, "Fatal Fissure", zone=Zone.HAND)
    victim = filler(engine, "Victim", player="p2", power=1, toughness=1)
    land = filler(engine, "Our land", type_line="Land")
    other = filler(engine, "Their land", type_line="Land", player="p2")
    cast(engine, spell, targets=[victim])
    assert not land.is_creature and engine.state.pending_choice is None
    engine.rules.destroy(victim)
    engine.rules.put_triggers_on_stack()
    choice = engine.state.pending_choice
    assert choice["kind"] == "trigger_target"
    assert any(o.get("instance_id") == land.instance_id for o in choice["options"])
    assert not any(o.get("instance_id") == other.instance_id for o in choice["options"])
    answer(engine, pick_label("Our land"))
    engine.resolve_until_stable()
    assert land.is_creature and land.power == 4
