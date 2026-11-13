"""Banshee's rounded halves use each activation's announced X."""
import pytest

from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.events import EventType
from tests.support.deck_batch import card, filler, game, main_phase


def _board():
    engine = game()
    main_phase(engine)
    player = engine.state.player_by_id("p1")
    source = card(engine, "Banshee")
    target = filler(engine, "Target", player="p2", power=2, toughness=20)
    player.mana_pool.add("C", 12)
    return engine, player, source, target


@pytest.mark.parametrize("x,target_damage,self_damage", [(0, 0, 0), (1, 0, 1), (4, 2, 2), (5, 2, 3)])
def test_rounds_target_down_and_controller_up(x, target_damage, self_damage):
    engine, player, source, target = _board()
    a, b = specs_for(source.card), specs_for(source.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    engine.activate_ability(player, source, x=x, targets=[target])
    assert source.tapped and player.mana_pool.total() == 12 - x and player.life == 20
    engine.resolve_until_stable()
    assert target.damage_marked == target_damage and player.life == 20 - self_damage
    assert all(event.get("source_id") == source.instance_id and not event.get("combat")
               for event in engine.state.events_this_turn() if event.type == EventType.DAMAGE)


def test_targeting_controller_combines_both_halves_into_one_damage_occurrence():
    engine, player, source, target = _board()
    engine.activate_ability(player, source, x=5, targets=[player])
    engine.resolve_until_stable()
    assert player.life == 15
    hits = [event for event in engine.state.events_this_turn() if event.type == EventType.DAMAGE]
    assert len(hits) == 1 and hits[0].get("amount") == 5


def test_may_target_opponent_player():
    engine, player, source, target = _board()
    opponent = engine.state.player_by_id("p2")
    engine.activate_ability(player, source, x=5, targets=[opponent])
    engine.resolve_until_stable()
    assert opponent.life == 18 and player.life == 17


def test_illegal_target_stops_recoil_too():
    engine, player, source, target = _board()
    engine.activate_ability(player, source, x=5, targets=[target])
    engine.rules.exile(target)
    engine.resolve_until_stable()
    assert player.life == 20


def test_overlapping_activations_retain_their_own_x():
    engine, player, source, target = _board()
    engine.activate_ability(player, source, x=3, targets=[target])
    engine.rules.set_tapped(source, False)
    engine.activate_ability(player, source, x=6, targets=[target])
    engine.rules.resolve_top_of_stack()
    assert target.damage_marked == 3 and player.life == 17
    engine.resolve_until_stable()
    assert target.damage_marked == 4 and player.life == 15


def test_clone_keeps_announced_x():
    engine, player, source, target = _board()
    engine.activate_ability(player, source, x=5, targets=[target])
    clone = GameEngine(engine.state.clone())
    clone.resolve_until_stable()
    assert clone.state.find_object(target.instance_id).damage_marked == 2
    assert clone.state.player_by_id("p1").life == 17 and player.life == 20


def test_lifelink_applies_to_both_halves_in_one_damage_batch():
    engine, player, source, target = _board()
    source.temp_keywords.add("lifelink")
    engine.activate_ability(player, source, x=5, targets=[target])
    engine.resolve_until_stable()
    assert player.life == 22  # three recoil damage, five life gained
    gains = [event for event in engine.state.events_this_turn() if event.type == EventType.LIFE_GAINED]
    assert len(gains) == 1 and gains[0].get("amount") == 5
