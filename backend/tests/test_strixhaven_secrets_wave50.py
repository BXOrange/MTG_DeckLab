"""Secrets of Strixhaven — playability batch, wave 50 (PAR-60).

Quintorius, History Chaser (planeswalker) — parser-claimed graveyard-exit
token trigger folds in; the +1 uses the new ``may_discard_then_draw_mill``
effect (loot with a fixed payoff), the -4 reuses ``pump`` with a
``subtypes`` filter over a ``selector`` group.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.ability_catalogue import _REGISTRY, is_registered
from mtg_analyzer.game.binding.core import bind_ability
from mtg_analyzer.game.effects.core import EffectRegistry
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone


def test_quintorius_registered_and_binds():
    assert is_registered("Quintorius, History Chaser")
    specs = _REGISTRY["quintorius, history chaser"]()
    assert len(specs) == 3
    src = GameObject(card=Card(id="q", name="Quintorius, History Chaser",
                              type_line="Legendary Planeswalker — Quintorius"),
                     owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    for s in specs:
        s.validate()
        bind_ability(s, src)

    trig, plus1, minus4 = specs
    assert trig.ability_kind == "triggered"
    assert plus1.cost == {"loyalty": 1}
    assert plus1.effects[0].type == "may_discard_then_draw_mill"
    assert minus4.cost == {"loyalty": -4}
    pump = minus4.effects[0]
    assert pump.type == "pump"
    assert pump.params["subtypes"] == ["Spirit"]
    assert set(pump.params["keywords"]) == {"double_strike", "vigilance"}


def test_may_discard_then_draw_mill_runtime():
    """Discarding a card draws 2 and mills 1; declining does nothing."""
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_hand=0, starting_life=20)
    p1, _ = eng.state.players
    for i in range(3):
        p1.hand.append(GameObject(card=Card(id=f"h{i}", name=f"Card{i}", type_line="Instant"),
                                  owner_id=p1.id, zone=Zone.HAND))
    for i in range(10):
        p1.library.append(GameObject(card=Card(id=f"l{i}", name=f"Lib{i}", type_line="Instant"),
                                     owner_id=p1.id, zone=Zone.LIBRARY))
    src = GameObject(card=Card(id="q", name="Quintorius, History Chaser",
                              type_line="Legendary Planeswalker — Quintorius"),
                     owner_id=p1.id, zone=Zone.BATTLEFIELD)
    src.controller_id = p1.id
    eng.state.add_to_battlefield(src)

    eff = EffectRegistry.create("may_discard_then_draw_mill", {"draw": 2, "mill": 1})
    eff.source = src
    eff.apply(eng.rules.context)
    # Answer the interactive discard: pitch the first hand card.
    assert eng.state.pending_choice and eng.state.pending_choice.get("kind") == "choose_objects"
    eng.rules.resolve_choose_objects_choice(p1.hand[0].instance_id)
    eng.resolve_until_stable()

    # discarded 1 -> hand 3-1+2 = 4; library 10-2 (draw) -1 (mill) = 7; gy 2
    assert len(p1.hand) == 4
    assert len(p1.library) == 7
    assert len(p1.graveyard) == 2
