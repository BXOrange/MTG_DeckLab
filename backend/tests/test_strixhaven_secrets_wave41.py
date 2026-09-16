"""Secrets of Strixhaven — playability batch, wave 41 (PAR-60).

"for each time you've cast your commander from the command zone" —
hand-authored in `game/card_registry/commander_cards.py`. Engine:
`continuous.count_selector` ``commander_casts_this_game``.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.card_registry import _REGISTRY, is_registered
from mtg_analyzer.game.binding.core import bind_ability
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone

WAVE41 = ["Vanguard of the Restless", "Commander's Insight"]


@pytest.mark.parametrize("name", WAVE41)
def test_registered_and_binds(name):
    assert is_registered(name)
    specs = _REGISTRY[name.lower()]()
    assert specs
    src = GameObject(card=Card(id="x", name=name, type_line="Creature", is_creature=True),
                     owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    for s in specs:
        s.validate()
        bind_ability(s, src)


def test_commander_casts_this_game_selector():
    from mtg_analyzer.game.continuous import count_selector
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_hand=0, starting_life=20)
    p1 = eng.state.active_player
    assert count_selector(eng.state, p1.id, "commander_casts_this_game") == 0
    p1.commander_casts["cmd1"] = 2
    p1.commander_casts["cmd2"] = 1
    assert count_selector(eng.state, p1.id, "commander_casts_this_game") == 3
