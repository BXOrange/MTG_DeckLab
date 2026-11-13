"""Kongming's Contraptions requires a player attack in this declare-attackers step."""
import pytest

from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from tests.support.deck_batch import card, filler, game
from tests.support.star_trek import advance_to


def _board(defender="p2"):
    engine = game(players=3)
    contraptions = card(engine, "Kongming's Contraptions", player="p2")
    attacker = filler(engine, "Attacker", power=3, toughness=4)
    advance_to(engine, "declare_attackers")
    if defender:
        engine.declare_attackers(engine.state.player_by_id("p1"), [{
            "attacker": attacker, "defender": engine.state.player_by_id(defender),
        }])
    return engine, contraptions, attacker


def test_activates_during_declare_attackers_and_deals_two_to_attacking_creature():
    engine, source, attacker = _board()
    a, b = specs_for(source.card), specs_for(source.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    engine.activate_ability(engine.state.player_by_id("p2"), source, targets=[attacker])
    assert source.tapped and attacker.damage_marked == 0
    engine.resolve_until_stable()
    assert attacker.damage_marked == 2


@pytest.mark.parametrize("defender", [None, "p3"])
def test_cannot_activate_before_attack_or_when_only_another_player_was_attacked(defender):
    engine, source, attacker = _board(defender)
    with pytest.raises(ValueError):
        engine.activate_ability(engine.state.player_by_id("p2"), source, targets=[attacker])
    assert not source.tapped


def test_cannot_activate_after_declare_attackers_step():
    engine, source, attacker = _board()
    advance_to(engine, "declare_blockers")
    with pytest.raises(ValueError):
        engine.activate_ability(engine.state.player_by_id("p2"), source, targets=[attacker])
    assert not source.tapped


def test_may_target_an_attacker_going_elsewhere_once_you_were_attacked():
    engine, source, attacker = _board(None)
    other = filler(engine, "Other attacker", power=3, toughness=4)
    engine.declare_attackers(engine.state.player_by_id("p1"), [
        {"attacker": attacker, "defender": engine.state.player_by_id("p2")},
        {"attacker": other, "defender": engine.state.player_by_id("p3")},
    ])
    engine.activate_ability(engine.state.player_by_id("p2"), source, targets=[other])
    engine.resolve_until_stable()
    assert other.damage_marked == 2 and attacker.damage_marked == 0


def test_nonattacking_target_is_illegal_even_after_you_were_attacked():
    engine, source, attacker = _board()
    idle = filler(engine, "Idle", power=3, toughness=4)
    with pytest.raises(ValueError):
        engine.activate_ability(engine.state.player_by_id("p2"), source, targets=[idle])
    assert not source.tapped


def test_clone_retains_the_attack_history():
    engine, source, attacker = _board()
    clone = GameEngine(engine.state.clone())
    clone.activate_ability(clone.state.player_by_id("p2"), clone.state.find_object(source.instance_id),
                           targets=[clone.state.find_object(attacker.instance_id)])
    clone.resolve_until_stable()
    assert clone.state.find_object(attacker.instance_id).damage_marked == 2
    assert attacker.damage_marked == 0 and not source.tapped
