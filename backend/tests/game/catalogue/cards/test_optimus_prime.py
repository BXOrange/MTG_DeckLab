"""Optimus Prime's two faces, bolster referent, and delayed conversion."""
import pytest

from mtg_analyzer.game import combat
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import answer, card, cast, filler, game


NAME = "Optimus Prime, Hero"


def _board(converted=False):
    engine = game()
    source = card(engine, NAME)
    if converted:
        engine.rules.transform_permanent(source)
        engine.recompute_continuous_effects()
    return engine, source, engine.state.player_by_id("p1"), engine.state.player_by_id("p2")


def _attack(engine, player, opponent, attackers):
    from tests.support.star_trek import advance_to
    advance_to(engine, "declare_attackers")
    engine.declare_attackers(player, [{"attacker": obj, "defender": opponent} for obj in attackers])
    engine.advance_step()
    engine.resolve_until_stable()


@pytest.mark.parametrize("active", [0, 1])
def test_front_bolsters_at_each_players_end_step(active):
    engine, source, player, opponent = _board()
    little = filler(engine, "Little", power=1, toughness=1)
    engine.state.active_player_index = active
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="end"))
    engine.resolve_until_stable()
    assert little.counters == {"+1/+1": 1} and not source.counters


def test_dies_returns_converted_under_owner_control():
    engine, source, player, opponent = _board()
    source.controller_id = "p2"
    engine.rules.put_into_graveyard(source)
    engine.resolve_until_stable()
    assert source.zone == Zone.BATTLEFIELD and source.transformed and source.controller_id == "p1"
    assert source.is_creature


def test_old_death_trigger_cannot_return_a_later_graveyard_visit():
    engine, source, player, opponent = _board()
    engine.rules.put_into_graveyard(source)
    engine.rules.put_triggers_on_stack()
    engine.rules.return_from_graveyard(source, "hand")
    player.hand.remove(source)
    player.add_to_zone(source, Zone.GRAVEYARD)
    engine.resolve_until_stable()
    assert source.zone == Zone.GRAVEYARD


def test_attack_bolsters_once_and_can_choose_a_nonattacking_creature():
    engine, source, player, opponent = _board(converted=True)
    a = filler(engine, "Attacker A", power=3, toughness=3)
    b = filler(engine, "Attacker B", power=3, toughness=3)
    little = filler(engine, "Not attacking", power=1, toughness=1)
    _attack(engine, player, opponent, [a, b])
    assert little.counters == {"+1/+1": 2} and combat.has(little, "trample")
    assert not a.counters and not b.counters and len(engine.state.turn_scoped_triggers) == 1


def test_bolster_tie_is_untargeted_and_remembers_the_chosen_creature():
    engine, source, player, opponent = _board(converted=True)
    a = filler(engine, "A", power=2, toughness=2)
    b = filler(engine, "B", power=2, toughness=2)
    b.temp_keywords.update({"hexproof", "shroud"})
    _attack(engine, player, opponent, [a])
    pending = engine.state.pending_choice
    assert pending["kind"] == "optimus_bolster" and not pending["optional"]
    assert {o["instance_id"] for o in pending["options"]} == {a.instance_id, b.instance_id}
    engine.resolve_pending_choice(str(b.instance_id))
    engine.resolve_until_stable()
    assert b.counters == {"+1/+1": 2} and not a.counters
    engine.rules.deal_damage(opponent, 1, source=a, combat=True)
    engine.resolve_until_stable()
    assert source.transformed
    engine.rules.deal_damage(opponent, 1, source=b, combat=True)
    engine.resolve_until_stable()
    assert not source.transformed


def test_delayed_conversion_repeats_within_its_stated_turn_duration():
    engine, source, player, opponent = _board(converted=True)
    attacker = filler(engine, "Attacker", power=1, toughness=1)
    _attack(engine, player, opponent, [attacker])
    for expected in (False, True):
        engine.rules.deal_damage(opponent, 1, source=attacker, combat=True)
        engine.resolve_until_stable()
        assert source.transformed == expected


def test_noncombat_and_creature_damage_do_not_convert():
    engine, source, player, opponent = _board(converted=True)
    attacker = filler(engine, "Attacker", power=1, toughness=1)
    victim = filler(engine, "Victim", player="p2", power=1, toughness=10)
    _attack(engine, player, opponent, [attacker])
    engine.rules.deal_damage(opponent, 1, source=attacker)
    engine.rules.deal_damage(victim, 1, source=attacker, combat=True)
    engine.resolve_until_stable()
    assert source.transformed


def test_more_than_meets_the_eye_casts_the_complete_back_face():
    engine = game()
    source = card(engine, NAME, zone=Zone.HAND)
    cast(engine, source, face="converted", pool={"C": 2, "U": 1, "R": 1, "W": 1})
    assert source.transformed and source.is_creature and combat.has(source, "trample")
    assert len(source.triggered_abilities) == 1


def test_split_attack_triggers_only_one_bolster():
    from tests.support.star_trek import advance_to
    engine = game(players=3)
    source = card(engine, NAME)
    engine.rules.transform_permanent(source)
    a = filler(engine, "A", power=3, toughness=3)
    b = filler(engine, "B", power=3, toughness=3)
    little = filler(engine, "Little", power=1, toughness=1)
    advance_to(engine, "declare_attackers")
    engine.declare_attackers(engine.state.player_by_id("p1"), [
        {"attacker": a, "defender": engine.state.player_by_id("p2")},
        {"attacker": b, "defender": engine.state.player_by_id("p3")},
    ])
    engine.advance_step()
    engine.resolve_until_stable()
    assert little.counters == {"+1/+1": 2} and len(engine.state.turn_scoped_triggers) == 1


def test_selected_creature_can_change_control_and_still_convert_source():
    engine, source, player, opponent = _board(converted=True)
    attacker = filler(engine, "Attacker", power=1, toughness=1)
    _attack(engine, player, opponent, [attacker])
    attacker.controller_id = "p2"
    engine.rules.deal_damage(player, 1, source=attacker, combat=True)
    engine.resolve_until_stable()
    assert not source.transformed


def test_selected_creature_new_visit_does_not_trigger_conversion():
    engine, source, player, opponent = _board(converted=True)
    attacker = filler(engine, "Attacker", power=1, toughness=1)
    _attack(engine, player, opponent, [attacker])
    engine.rules.put_into_graveyard(attacker)
    engine.rules.return_from_graveyard(attacker, "battlefield")
    engine.rules.deal_damage(opponent, 1, source=attacker, combat=True)
    engine.resolve_until_stable()
    assert source.transformed


def test_source_new_visit_is_not_converted_by_old_delayed_ability():
    engine, source, player, opponent = _board(converted=True)
    attacker = filler(engine, "Attacker", power=1, toughness=1)
    _attack(engine, player, opponent, [attacker])
    engine.rules.exile(source)
    engine.rules.return_from_graveyard(source, "battlefield")
    assert not source.transformed
    engine.rules.deal_damage(opponent, 1, source=attacker, combat=True)
    engine.resolve_until_stable()
    assert not source.transformed


def test_delayed_ability_survives_the_chosen_creature_leaving_after_damage():
    engine, source, player, opponent = _board(converted=True)
    attacker = filler(engine, "Attacker", power=1, toughness=1)
    _attack(engine, player, opponent, [attacker])
    engine.rules.deal_damage(opponent, 1, source=attacker, combat=True)
    engine.rules.put_triggers_on_stack()
    engine.rules.put_into_graveyard(attacker)
    engine.resolve_until_stable()
    assert not source.transformed


def test_trample_expires_at_cleanup_and_delayed_ability_expires_next_turn():
    engine, source, player, opponent = _board(converted=True)
    attacker = filler(engine, "Attacker", power=1, toughness=1)
    _attack(engine, player, opponent, [attacker])
    engine._step_cleanup()
    assert not combat.has(attacker, "trample")
    engine.state.internal_turn.number += 1
    engine.rules.deal_damage(opponent, 1, source=attacker, combat=True)
    engine.resolve_until_stable()
    assert source.transformed and not engine.state.turn_scoped_triggers


def test_tie_choice_and_delayed_trigger_survive_clone():
    engine, source, player, opponent = _board(converted=True)
    a = filler(engine, "A", power=2, toughness=2)
    b = filler(engine, "B", power=2, toughness=2)
    _attack(engine, player, opponent, [a])
    clone = GameEngine(engine.state.clone())
    clone.resolve_pending_choice(str(b.instance_id))
    clone.resolve_until_stable()
    clone2 = GameEngine(clone.state.clone())
    clone2.rules.deal_damage(clone2.state.player_by_id("p2"), 1,
                             source=clone2.state.find_object(b.instance_id), combat=True)
    clone2.resolve_until_stable()
    assert not clone2.state.find_object(source.instance_id).transformed
    assert source.transformed and not b.counters and engine.state.pending_choice is not None


def test_specs_are_fresh_on_both_faces():
    from mtg_analyzer.game.card_registry import specs_for
    engine, source, player, opponent = _board()
    for index in (0, 2):
        first, second = specs_for(source.card), specs_for(source.card)
        assert first[index] is not second[index] and first[index].effects[0] is not second[index].effects[0]
        engine.rules.transform_permanent(source)
