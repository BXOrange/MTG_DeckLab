"""Secrets of Strixhaven — playability batch, wave 28 (PAR-60).

Prismari "Artistry": instant/sorcery cast-matters payoffs, hand-authored in
`game/card_registry/commander_cards.py`. Engine change:
`PumpEffect.amount_from_count_selector_axis` now also governs the
``amount_from_trigger_event`` path (Renegade Bull's +X/+0).
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.card_registry import _REGISTRY, is_registered
from mtg_analyzer.game.binding.core import bind_ability, build_effects
from mtg_analyzer.game.effects.core import GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.spec import EffectSpec

WAVE28 = ["Prismari Pianist", "Manaform Hellkite", "Leitmotif Composer",
          "Renegade Bull", "Deekah, Fractal Theorist", "Galazeth Prismari"]


@pytest.mark.parametrize("name", WAVE28)
def test_registered_and_binds(name):
    assert is_registered(name)
    specs = _REGISTRY[name.lower()]()
    assert specs
    src = GameObject(card=Card(id="x", name=name, type_line="Creature"),
                     owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    for s in specs:
        s.validate()
        bind_ability(s, src)


def test_renegade_bull_pumps_power_only_by_spell_mana_value():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_hand=0, starting_life=20)
    p1 = eng.state.active_player
    bull = GameObject(card=Card(id="rb", name="Renegade Bull", type_line="Creature — Ox",
                               is_creature=True, power=3, toughness=3),
                      owner_id=p1.id, zone=Zone.BATTLEFIELD)
    bull.controller_id = p1.id
    eng.state.add_to_battlefield(bull)
    spec = _REGISTRY["renegade bull"]()[0]
    effs = build_effects(spec.effects, bull)
    ctx = GameContext(state=eng.state, engine=eng.rules)
    ctx.trigger_event = {"mana_value": 4}
    for e in effs:
        e.apply(ctx, [])
    eng.recompute_continuous_effects()
    assert (bull.power, bull.toughness) == (7, 3)  # +4/+0, not +4/+4


def test_prismari_pianist_two_gated_triggers():
    specs = _REGISTRY["prismari pianist"]()
    assert len(specs) == 2
    small, big = specs
    assert small.trigger["spell_mana_value_at_most"] == 4
    assert small.effects[0].params["count"] == 1
    assert big.trigger["spell_mana_value_at_least"] == 5
    assert big.effects[0].params["count"] == 3
