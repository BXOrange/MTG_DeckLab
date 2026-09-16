"""Secrets of Strixhaven — playability batch, waves 38-39 (PAR-60).

wave 38: Curse of the Swine, Forum Filibuster (existing primitives).
wave 39: Gyome / Jadar — new `GameState.nontoken_creatures_entered_this_turn`
per-turn tracker + `continuous.count_selector`
``nontoken_creatures_you_entered_this_turn``; `static_conditions` kind
``control_no_creatures_with_keyword``.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import static_conditions
from mtg_analyzer.game.card_registry import _REGISTRY, is_registered
from mtg_analyzer.game.binding.core import bind_ability
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone

WAVE = ["Curse of the Swine", "Forum Filibuster", "Gyome, Master Chef",
        "Jadar, Ghoulcaller of Nephalia"]


@pytest.mark.parametrize("name", WAVE)
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


def test_nontoken_creatures_entered_tracker():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_hand=0, starting_life=20)
    p1 = eng.state.active_player
    from mtg_analyzer.game.continuous import count_selector
    assert count_selector(eng.state, p1.id,
                          "nontoken_creatures_you_entered_this_turn") == 0

    def add(name, is_tok, is_cre=True):
        o = GameObject(card=Card(id=name, name=name, type_line="Creature — Bear",
                                 is_creature=is_cre), owner_id=p1.id, zone=Zone.HAND)
        o.controller_id = p1.id
        o.is_token = is_tok
        eng.state.add_to_battlefield(o)

    add("Real1", False)
    add("Real2", False)
    add("Tok", True)
    add("Land", False, is_cre=False)
    assert count_selector(eng.state, p1.id,
                          "nontoken_creatures_you_entered_this_turn") == 2


def test_control_no_creatures_with_keyword_condition():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_hand=0, starting_life=20)
    p1 = eng.state.active_player
    cond = {"kind": "control_no_creatures_with_keyword", "keyword": "decayed"}
    assert static_conditions.condition_holds(cond, eng.state, None, p1.id) is True

    z = GameObject(card=Card(id="z", name="Zombie", type_line="Creature — Zombie",
                            is_creature=True), owner_id=p1.id, zone=Zone.BATTLEFIELD)
    z.controller_id = p1.id
    z.intrinsic_keywords.add("decayed")
    eng.state.add_to_battlefield(z)
    assert static_conditions.condition_holds(cond, eng.state, None, p1.id) is False
