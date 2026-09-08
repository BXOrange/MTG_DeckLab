"""Planeswalker loyalty abilities (RULE 606) — enter, activate, SBA."""

import pytest

from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.binding.core import bind_from_catalogue


def walker(name="Chandra", loyalty=4, oracle_text="[+1]: Draw a card.\n[-2]: Draw a card."):
    return Card(id=name, name=name, type_line="Legendary Planeswalker — Chandra",
                loyalty=loyalty, oracle_text=oracle_text)


def make_engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])],
        starting_life=20, starting_hand=0,
    )


def _put_walker(eng, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, is_commander=False)
    bind_from_catalogue(obj)
    obj.summoning_sick = False
    eng.state.add_to_battlefield(obj)
    return obj


def _main_phase(eng):
    eng.begin_turn()
    eng.state.current_step = "main1"


def test_planeswalker_enters_with_starting_loyalty():
    eng = make_engine()
    obj = _put_walker(eng, walker(loyalty=4))
    assert obj.loyalty == 4
    assert obj.to_dict()["loyalty"] == 4


def test_plus_ability_adds_loyalty_and_is_once_per_turn():
    eng = make_engine()
    _main_phase(eng)
    obj = _put_walker(eng, walker(loyalty=4))
    plus = obj.activated_abilities[0]  # [+1]
    assert plus.cost.is_loyalty and plus.cost.loyalty == 1
    assert eng.can_activate(eng.state.active_player, obj, plus)
    eng.activate_ability(eng.state.active_player, obj, 0)
    assert obj.loyalty == 5
    # RULE 606.3: only one loyalty ability per turn.
    assert not eng.can_activate(eng.state.active_player, obj, plus)


def test_minus_ability_requires_enough_loyalty():
    eng = make_engine()
    _main_phase(eng)
    obj = _put_walker(eng, walker(loyalty=1))
    minus = obj.activated_abilities[1]  # [-2]
    assert minus.cost.loyalty == -2
    # Only 1 loyalty, can't pay [-2].
    assert not eng.can_activate(eng.state.active_player, obj, minus)
    obj.counters["loyalty"] = 3
    assert eng.can_activate(eng.state.active_player, obj, minus)
    eng.activate_ability(eng.state.active_player, obj, 1)
    assert obj.loyalty == 1


def test_loyalty_ability_is_sorcery_speed_only():
    eng = make_engine()
    _main_phase(eng)
    obj = _put_walker(eng, walker())
    plus = obj.activated_abilities[0]
    # With something on the stack, no loyalty activation (RULE 606.3).
    eng.state.stack.append(object())
    assert not eng.can_activate(eng.state.active_player, obj, plus)
    eng.state.stack.clear()
    assert eng.can_activate(eng.state.active_player, obj, plus)


def test_loyalty_resets_next_turn():
    eng = make_engine()
    _main_phase(eng)
    obj = _put_walker(eng, walker())
    eng.activate_ability(eng.state.active_player, obj, 0)
    assert obj.activated_loyalty_this_turn
    eng._step_untap()
    assert not obj.activated_loyalty_this_turn


def test_planeswalker_dies_at_zero_loyalty():
    eng = make_engine()
    obj = _put_walker(eng, walker(loyalty=2))
    obj.add_counters("loyalty", -2)  # e.g. from damage
    eng.rules.check_state_based_actions()
    # RULE 704.5i: 0 loyalty → owner's graveyard.
    assert obj not in eng.state.battlefield
    assert obj in eng.state.player_by_id("p1").graveyard
