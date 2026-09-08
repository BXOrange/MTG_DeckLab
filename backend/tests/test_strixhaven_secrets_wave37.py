"""Secrets of Strixhaven — playability batch, wave 37 (PAR-60).

A few more tractable singletons hand-authored in
`game/ability_catalogue/commander_cards.py`. Engine: `ConditionalEffect` gained
``previous_target_power_at_least`` (Yavimaya Bloomsage).
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.ability_catalogue import _REGISTRY, is_registered
from mtg_analyzer.game.binding.core import bind_ability
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone

WAVE37 = ["Yavimaya Bloomsage", "Herald of Amity"]


@pytest.mark.parametrize("name", WAVE37)
def test_registered_and_binds(name):
    assert is_registered(name)
    specs = _REGISTRY[name.lower()]()
    assert specs
    src = GameObject(card=Card(id="x", name=name, type_line="Creature", is_creature=True,
                              power=2, toughness=2),
                     owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    for s in specs:
        s.validate()
        bind_ability(s, src)


def test_previous_target_power_at_least_condition():
    from mtg_analyzer.game.effects.core import ConditionalEffect, GameContext, BecomePreparedEffect
    from mtg_analyzer.game.game_engine import GameEngine
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_hand=0, starting_life=20)
    p1 = eng.state.active_player
    beefy = GameObject(card=Card(id="be", name="Beefy", type_line="Creature — Ox",
                               is_creature=True, power=8, toughness=8),
                       owner_id=p1.id, zone=Zone.BATTLEFIELD)
    beefy.controller_id = p1.id
    eng.state.add_to_battlefield(beefy)
    weak = GameObject(card=Card(id="wk", name="Weak", type_line="Creature — Bird",
                              is_creature=True, power=1, toughness=1),
                      owner_id=p1.id, zone=Zone.BATTLEFIELD)
    weak.controller_id = p1.id
    eng.state.add_to_battlefield(weak)

    ce = ConditionalEffect({"previous_target_power_at_least": 7}, BecomePreparedEffect())
    ctx = GameContext(state=eng.state, engine=eng.rules)
    ctx.previous_targets = [beefy]
    assert ce._condition_holds(ctx, None) is True
    ctx.previous_targets = [weak]
    assert ce._condition_holds(ctx, None) is False
