"""Secrets of Strixhaven — playability batch, wave 26 (PAR-60).

Lorehold "land catch-up" + "a card left your graveyard this turn", hand-authored
in `game/ability_catalogue/entries_019.py`. New engine primitives:
`static_conditions` kinds ``opponent_controls_more_lands`` and
``card_left_graveyard_this_turn`` (the latter backed by the new
`GameState.cards_left_graveyard_this_turn` per-turn set, recorded at
`RulesEngine._note_graveyard_exit`, cleared each `begin_turn`).
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import static_conditions
from mtg_analyzer.game.ability_catalogue import _REGISTRY, is_registered
from mtg_analyzer.game.effect_binder import bind_ability
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone

WAVE26 = ["Land Tax", "Archaeomancer's Map", "Claim Jumper", "Primary Research",
          "Relic Retriever"]


@pytest.mark.parametrize("name", WAVE26)
def test_registered_and_binds(name):
    assert is_registered(name)
    specs = _REGISTRY[name.lower()]()
    assert specs
    src = GameObject(card=Card(id="x", name=name, type_line="Enchantment"),
                     owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    for s in specs:
        s.validate()
        bind_ability(s, src)


def _eng():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_hand=0, starting_life=20)
    p1 = eng.state.active_player
    p2 = [p for p in eng.state.players if p.id != p1.id][0]
    return eng, p1, p2


def _land(eng, pid, i):
    o = GameObject(card=Card(id=f"{pid}L{i}", name="Plains", type_line="Basic Land — Plains",
                             is_land=True), owner_id=pid, zone=Zone.BATTLEFIELD)
    o.controller_id = pid
    eng.state.add_to_battlefield(o)
    return o


def test_opponent_controls_more_lands_condition():
    eng, p1, p2 = _eng()
    cond = {"kind": "opponent_controls_more_lands"}
    _land(eng, p1.id, 0)
    _land(eng, p1.id, 1)
    _land(eng, p2.id, 0)
    assert static_conditions.condition_holds(cond, eng.state, None, p1.id) is False
    _land(eng, p2.id, 1)
    _land(eng, p2.id, 2)
    assert static_conditions.condition_holds(cond, eng.state, None, p1.id) is True


def test_card_left_graveyard_this_turn_tracker():
    eng, p1, p2 = _eng()
    cond = {"kind": "card_left_graveyard_this_turn"}
    assert static_conditions.condition_holds(cond, eng.state, None, p1.id) is False
    # put a card in p1's graveyard, then move it out via the exit choke point
    obj = GameObject(card=Card(id="g1", name="Bolt", type_line="Instant"),
                     owner_id=p1.id, zone=Zone.GRAVEYARD)
    p1.graveyard.append(obj)
    eng.rules._note_graveyard_exit(obj)
    assert static_conditions.condition_holds(cond, eng.state, None, p1.id) is True
    assert static_conditions.condition_holds(cond, eng.state, None, p2.id) is False
