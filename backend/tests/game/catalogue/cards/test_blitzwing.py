"""Both Blitzwing faces: historical life loss, random abilities, and conversion."""
import pytest

from mtg_analyzer.game import combat
from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, cast, filler, game, answer


NAME = "Blitzwing, Cruel Tormentor"


def _board(converted=False):
    engine = game()
    source = card(engine, NAME)
    if converted:
        assert engine.rules.transform_permanent(source)
        engine.recompute_continuous_effects()
    return engine, source, engine.state.player_by_id("p2")


def _step(engine, step):
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, step=step))
    engine.resolve_until_stable()
    answer(engine)
    engine.resolve_until_stable()


def _queue(engine, step):
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, step=step))
    engine.rules.put_triggers_on_stack()
    if engine.state.pending_choice and engine.state.pending_choice["kind"] == "trigger_target":
        engine.rules.resolve_choice("p2")


def test_front_echoes_total_life_lost_even_if_life_was_gained():
    engine, source, opponent = _board()
    engine.rules.lose_life(opponent, 4)
    engine.rules.gain_life(opponent, 7)
    _step(engine, "end")
    assert opponent.life == 19 and engine.state.life_lost_this_turn[opponent.id] == 8
    assert not source.transformed


def test_no_life_loss_converts_to_living_metal_vehicle():
    engine, source, opponent = _board()
    _step(engine, "end")
    assert source.transformed and opponent.life == 20
    assert source.is_creature and source.has_subtype("Vehicle")
    engine.state.active_player_index = 1
    engine.recompute_continuous_effects()
    assert not source.is_creature and source.is_artifact


def test_front_does_not_trigger_on_an_opponents_end_step():
    engine, source, opponent = _board()
    engine.state.active_player_index = 1
    _step(engine, "end")
    assert not source.transformed


@pytest.mark.parametrize("chosen", ["flying", "indestructible"])
def test_back_randomly_gains_one_ability_until_cleanup(monkeypatch, chosen):
    engine, source, opponent = _board(converted=True)
    seen = []
    def choose(options):
        seen.append(tuple(options))
        return chosen
    monkeypatch.setattr(engine.rules, "random_choice", choose)
    _step(engine, "begin_combat")
    assert seen == [("flying", "indestructible")]
    assert combat.has(source, chosen)
    assert not combat.has(source, "indestructible" if chosen == "flying" else "flying")
    engine._step_cleanup()
    assert not combat.has(source, chosen)


def test_back_does_not_roll_on_an_opponents_combat():
    engine, source, opponent = _board(converted=True)
    before = engine.state.rng_counter
    engine.state.active_player_index = 1
    _step(engine, "begin_combat")
    assert engine.state.rng_counter == before and not source.temp_keywords


@pytest.mark.parametrize("combat_damage,is_player,converts", [(True, True, True), (False, True, False), (True, False, False)])
def test_back_only_converts_for_its_combat_damage_to_a_player(combat_damage, is_player, converts):
    engine, source, opponent = _board(converted=True)
    victim = opponent if is_player else filler(engine, "Victim", player="p2", power=2, toughness=10)
    engine.rules.deal_damage(victim, 1, source=source, combat=combat_damage)
    engine.resolve_until_stable()
    assert source.transformed is not converts


def test_cast_converted_for_more_than_meets_the_eye_binds_both_triggers():
    engine = game()
    source = card(engine, NAME, zone=Zone.HAND)
    cast(engine, source, face="converted", pool={"B": 1, "C": 3})
    assert source.transformed and source.is_creature
    assert len(source.triggered_abilities) == 2
    assert engine.state.player_by_id("p1").mana_pool.total() == 0
    a, b = specs_for(source.card), specs_for(source.card)
    assert a[1] is not b[1] and a[1].effects[0] is not b[1].effects[0]


def test_rng_and_trigger_survive_clone():
    engine, source, opponent = _board(converted=True)
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="begin_combat"))
    engine.rules.put_triggers_on_stack()
    clone = GameEngine(engine.state.clone())
    engine.resolve_until_stable()
    clone.resolve_until_stable()
    assert source.temp_keywords == clone.state.find_object(source.instance_id).temp_keywords
    assert len(source.temp_keywords) == 1 and engine.state.rng_counter == clone.state.rng_counter


def test_front_measures_life_loss_at_resolution_not_trigger_time():
    engine, source, opponent = _board()
    engine.rules.lose_life(opponent, 2)
    _queue(engine, "end")
    assert len(engine.state.stack) == 1
    engine.rules.lose_life(opponent, 3)
    engine.resolve_until_stable()
    assert opponent.life == 10 and not source.transformed


def test_front_converts_when_life_cannot_change_even_with_positive_history():
    from mtg_analyzer.game.effects.library import PlayerShieldEffect
    engine, source, opponent = _board()
    engine.rules.lose_life(opponent, 4)
    opponent.player_effects.append(PlayerShieldEffect(protection_from_everything=False))
    _step(engine, "end")
    assert source.transformed and opponent.life == 16


@pytest.mark.parametrize("step,converted", [("end", False), ("begin_combat", True)])
def test_departure_and_reentry_do_not_affect_the_new_visit(step, converted):
    engine, source, opponent = _board(converted=converted)
    _queue(engine, step)
    assert len(engine.state.stack) == 1
    engine.rules.put_into_graveyard(source)
    engine.rules.return_from_graveyard(source, "battlefield")
    engine.resolve_until_stable()
    assert not source.transformed and not source.temp_keywords


def test_front_ability_still_causes_life_loss_after_source_leaves():
    engine, source, opponent = _board()
    engine.rules.lose_life(opponent, 3)
    _queue(engine, "end")
    engine.rules.put_into_graveyard(source)
    engine.resolve_until_stable()
    assert opponent.life == 14 and source.zone == Zone.GRAVEYARD


def test_illegal_opponent_target_does_not_convert_source():
    from mtg_analyzer.game.effects.library import PlayerShieldEffect
    engine, source, opponent = _board()
    _queue(engine, "end")
    opponent.player_effects.append(PlayerShieldEffect())
    engine.resolve_until_stable()
    assert not source.transformed and opponent.life == 20


def test_random_ability_survives_conversion_until_cleanup(monkeypatch):
    engine, source, opponent = _board(converted=True)
    monkeypatch.setattr(engine.rules, "random_choice", lambda choices: "flying")
    _step(engine, "begin_combat")
    engine.rules.deal_damage(opponent, 1, source=source, combat=True)
    engine.resolve_until_stable()
    assert not source.transformed and combat.has(source, "flying")
    engine._step_cleanup()
    assert not combat.has(source, "flying")
