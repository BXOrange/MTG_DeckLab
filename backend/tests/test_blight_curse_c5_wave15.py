"""Blight Curse batch C5 wave 15 — Burning Curiosity
(hand-authored, `card_registry/blight_curse.py`).

* Optional ``blight 1`` additional cost (`additional_cost={"blight": 1}` +
  ``additional_cost_optional``).
* ``impulsive_draw`` whose count is overridden 2 -> 3 by the new
  ``count_if_additional_cost_paid`` param (RULE 614 "instead", gated on
  `GameObject.additional_cost_paid`).
"""

from __future__ import annotations

from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.game.binding.core import bind_from_catalogue, build_effects
from mtg_analyzer.game.effects.core import GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.spec import EffectSpec


BURNING_CURIOSITY = Card(
    id="BCU", name="Burning Curiosity", type_line="Sorcery", is_sorcery=True,
    mana_cost_string="{2}{R}", converted_mana_cost=3,
    oracle_text="As an additional cost to cast this spell, you may blight 1. (You may "
                "put a -1/-1 counter on a creature you control.)\nExile the top two cards "
                "of your library. If this spell's additional cost was paid, exile the top "
                "three cards instead. Until the end of your next turn, you may play those cards.",
)


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def _stock(eng, n=8):
    p1 = eng.state.players[0]
    for i in range(n):
        p1.library.append(GameObject(Card(id=f"L{i}", name=f"L{i}", type_line="Mountain",
                                          is_land=True), owner_id="p1", zone=Zone.LIBRARY))
    return p1


def _src(eng, additional_cost_paid=False):
    o = GameObject(BURNING_CURIOSITY, owner_id="p1", zone=Zone.STACK)
    o.controller_id = "p1"
    o.additional_cost_paid = additional_cost_paid
    bind_from_catalogue(o)
    return o


def test_burning_curiosity_authored():
    specs = specs_for(BURNING_CURIOSITY)
    assert len(specs) == 1
    assert specs[0].additional_cost == {"blight": 1}
    assert specs[0].additional_cost_optional is True
    p = specs[0].effects[0].params
    assert specs[0].effects[0].type == "impulsive_draw"
    assert p["count"] == 2 and p["count_if_additional_cost_paid"] == 3


def test_binds_the_optional_blight_additional_cost():
    eng = _engine()
    o = _src(eng)
    assert o.additional_cast_cost.blight == 1
    assert getattr(o, "additional_cast_cost_optional", False) is True


def test_exiles_two_when_the_cost_was_not_paid():
    eng = _engine()
    p1 = _stock(eng, 8)
    src = _src(eng, additional_cost_paid=False)
    eng.begin_turn()

    build_effects([EffectSpec("impulsive_draw", {"count": 2, "count_if_additional_cost_paid": 3})],
                  src)[0].apply(GameContext(eng.state, eng.rules), targets=None)

    assert len(p1.library) == 6
    assert len(p1.exile) == 2


def test_exiles_three_when_the_additional_cost_was_paid():
    eng = _engine()
    p1 = _stock(eng, 8)
    src = _src(eng, additional_cost_paid=True)
    eng.begin_turn()

    build_effects([EffectSpec("impulsive_draw", {"count": 2, "count_if_additional_cost_paid": 3})],
                  src)[0].apply(GameContext(eng.state, eng.rules), targets=None)

    assert len(p1.library) == 5
    assert len(p1.exile) == 3
