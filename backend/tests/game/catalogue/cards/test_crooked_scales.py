"""Crooked Scales keeps both targets throughout its paid coin-flip loop."""
import pytest

from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import activate, card, filler, game, main_phase


def _board(monkeypatch, rolls, reserve=0):
    engine = game()
    scales = card(engine, "Crooked Scales")
    own = filler(engine, "Own", power=2, toughness=2)
    enemy = filler(engine, "Enemy", player="p2", power=2, toughness=2)
    player = engine.state.player_by_id("p1")
    player.mana_pool.add("C", 4 + reserve)
    outcomes = iter(rolls)
    monkeypatch.setattr(engine.rules, "random_int", lambda n: next(outcomes))
    return engine, player, scales, own, enemy


def _flips(engine):
    return [event for event in engine.state.events_this_turn() if event.type == EventType.COIN_FLIP]


def test_winning_flip_destroys_only_opponents_target_and_pays_activation(monkeypatch):
    engine, player, scales, own, enemy = _board(monkeypatch, [0])
    a, b = specs_for(scales.card), specs_for(scales.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    assert len(scales.activated_abilities) == 1
    activate(engine, scales, targets=[enemy, own])
    assert enemy.zone == Zone.GRAVEYARD and own.zone == Zone.BATTLEFIELD
    assert scales.tapped and player.mana_pool.total() == 0
    assert len(_flips(engine)) == 1 and not engine.state.pending_choice


def test_losing_flip_with_no_mana_destroys_own_target(monkeypatch):
    engine, player, scales, own, enemy = _board(monkeypatch, [1])
    activate(engine, scales, targets=[enemy, own])
    assert own.zone == Zone.GRAVEYARD and enemy.zone == Zone.BATTLEFIELD
    assert not engine.state.pending_choice


def test_declining_payment_destroys_own_target_without_repeating(monkeypatch):
    engine, player, scales, own, enemy = _board(monkeypatch, [1], reserve=3)
    activate(engine, scales, targets=[enemy, own])
    assert engine.state.pending_choice["kind"] == "pay_cost_then"
    assert own.zone == enemy.zone == Zone.BATTLEFIELD
    engine.resolve_pending_choice("decline")
    assert own.zone == Zone.GRAVEYARD and enemy.zone == Zone.BATTLEFIELD
    assert player.mana_pool.total() == 3 and len(_flips(engine)) == 1


def test_pay_twice_and_win_uses_original_targets_and_no_new_activation_cost(monkeypatch):
    engine, player, scales, own, enemy = _board(monkeypatch, [1, 1, 0], reserve=6)
    bystander = filler(engine, "Other enemy", player="p2", power=2, toughness=2)
    activate(engine, scales, targets=[enemy, own])
    engine.resolve_pending_choice("pay")
    assert engine.state.pending_choice["kind"] == "pay_cost_then"
    assert own.zone == enemy.zone == Zone.BATTLEFIELD
    engine.resolve_pending_choice("pay")
    assert enemy.zone == Zone.GRAVEYARD and own.zone == bystander.zone == Zone.BATTLEFIELD
    assert player.mana_pool.total() == 0 and len(_flips(engine)) == 3


def test_repeated_loss_when_payment_is_exhausted_destroys_own_target(monkeypatch):
    engine, player, scales, own, enemy = _board(monkeypatch, [1, 1], reserve=3)
    activate(engine, scales, targets=[enemy, own])
    engine.resolve_pending_choice("pay")
    assert own.zone == Zone.GRAVEYARD and enemy.zone == Zone.BATTLEFIELD
    assert not engine.state.pending_choice and len(_flips(engine)) == 2


def test_clone_retains_the_payment_and_targets(monkeypatch):
    engine, player, scales, own, enemy = _board(monkeypatch, [1], reserve=3)
    activate(engine, scales, targets=[enemy, own])
    clone = GameEngine(engine.state.clone())
    monkeypatch.setattr(clone.rules, "random_int", lambda n: 0)
    clone.resolve_pending_choice("pay")
    assert clone.state.find_object(enemy.instance_id).zone == Zone.GRAVEYARD
    assert clone.state.find_object(own.instance_id).zone == Zone.BATTLEFIELD
    assert own.zone == enemy.zone == Zone.BATTLEFIELD


def test_both_targets_are_required_before_activation(monkeypatch):
    engine, player, scales, own, enemy = _board(monkeypatch, [])
    main_phase(engine)
    with pytest.raises(ValueError):
        engine.activate_ability(player, scales, targets=[enemy])
    assert not scales.tapped and not _flips(engine)


@pytest.mark.parametrize("departing,roll,destroyed", [
    ("enemy", 1, "own"), ("own", 0, "enemy"),
    ("enemy", 0, None), ("own", 1, None),
])
def test_illegal_target_does_not_shift_the_other_target_into_its_slot(monkeypatch, departing, roll, destroyed):
    engine, player, scales, own, enemy = _board(monkeypatch, [roll])
    main_phase(engine)
    engine.activate_ability(player, scales, targets=[enemy, own])
    engine.rules.exile(enemy if departing == "enemy" else own)
    engine.resolve_until_stable()
    surviving = own if departing == "enemy" else enemy
    assert surviving.zone == (Zone.GRAVEYARD if destroyed else Zone.BATTLEFIELD)
    assert len(_flips(engine)) == 1
