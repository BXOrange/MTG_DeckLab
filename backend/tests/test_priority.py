"""Interactive multiplayer priority (RULE 117) — the basic version.

`pass_priority()` with no argument keeps its solo/goldfish behaviour
unchanged (collapses to resolving the top of the stack immediately).
`pass_priority(player)` drives the real mechanic: priority only resolves
the stack once every living player has passed in succession, and any
player's real action reclaims priority for them.
"""

import pytest

from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.models.mana_cost import ManaCost
from mtg_analyzer.game.game_engine import GameEngine


def land(name="Forest", produces="Forest"):
    return Card(id=name, name=name, type_line=f"Basic Land — {produces}", is_land=True)


def instant(name="Shock", cost="{R}"):
    return Card(
        id=name, name=name, type_line="Instant",
        mana_cost_string=cost,
        converted_mana_cost=ManaCost.parse(cost).converted_mana_cost,
        is_instant=True,
    )


def make_engine():
    return GameEngine.new_game(
        [("p1", "Alice", [land()] * 5), ("p2", "Bob", [land()] * 5)],
        starting_life=20, starting_hand=0,
    )


def _hand_card(player, card):
    obj = GameObject(card, owner_id=player.id, zone=Zone.HAND)
    player.hand.append(obj)
    return obj


def test_active_player_gets_priority_at_turn_start():
    eng = make_engine()
    eng.begin_turn()
    assert eng.state.priority_player is eng.state.active_player


def test_solo_pass_priority_is_unaffected_by_the_new_mechanic():
    # No `player` arg: old, unconditional "resolve top of stack" behaviour.
    eng = make_engine()
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    bolt = _hand_card(p1, instant("Bolt", cost="{R}"))
    p1.mana_pool.add_many({"R": 1})
    eng.cast_spell(p1, bolt)
    assert eng.state.stack
    assert eng.pass_priority() is True
    assert not eng.state.stack


def test_non_holder_cannot_pass_priority():
    eng = make_engine()
    eng.begin_turn()  # p1 active, p1 holds priority
    p2 = eng.state.player_by_id("p2")
    with pytest.raises(ValueError):
        eng.pass_priority(p2)


def test_stack_waits_for_both_players_to_pass():
    eng = make_engine()
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p2 = eng.state.player_by_id("p2")
    bolt = _hand_card(p1, instant("Bolt", cost="{R}"))
    p1.mana_pool.add_many({"R": 1})
    eng.cast_spell(p1, bolt)  # p1 acted → p1 reclaims priority
    assert eng.state.priority_player is p1

    # p1 passes: not everyone has passed yet (p2 hasn't), so nothing resolves
    # and priority moves to p2.
    assert eng.pass_priority(p1) is False
    assert eng.state.stack  # still on the stack
    assert eng.state.priority_player is p2

    # p2 passes too: now everyone has passed, so the top of the stack resolves.
    assert eng.pass_priority(p2) is True
    assert not eng.state.stack


def test_responding_in_the_priority_window_resets_the_passes():
    eng = make_engine()
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p2 = eng.state.player_by_id("p2")
    bolt = _hand_card(p1, instant("Bolt", cost="{R}"))
    p1.mana_pool.add_many({"R": 1})
    eng.cast_spell(p1, bolt)

    assert eng.pass_priority(p1) is False  # p1 passes, waiting on p2
    assert eng.state.priority_player is p2

    # p2 responds instead of passing — casts their own instant.
    shock = _hand_card(p2, instant("Shock", cost="{R}"))
    p2.mana_pool.add_many({"R": 1})
    eng.cast_spell(p2, shock)
    assert len(eng.state.stack) == 2
    # p2's action reclaims priority; p1's earlier pass no longer counts.
    assert eng.state.priority_player is p2
    assert eng.pass_priority(p2) is False
    assert eng.state.priority_player is p1
    # Now both have passed on the current stack state (shock on top).
    assert eng.pass_priority(p1) is True
    assert len(eng.state.stack) == 1  # shock resolved, bolt remains


def test_priority_resets_to_active_player_after_something_resolves():
    eng = make_engine()
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p2 = eng.state.player_by_id("p2")
    bolt = _hand_card(p1, instant("Bolt", cost="{R}"))
    p1.mana_pool.add_many({"R": 1})
    eng.cast_spell(p1, bolt)
    eng.pass_priority(p1)
    eng.pass_priority(p2)  # resolves
    assert eng.state.priority_player is p1
    assert eng.state.priority_passed == set()
