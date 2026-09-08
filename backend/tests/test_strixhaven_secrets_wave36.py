"""Secrets of Strixhaven — playability batch, wave 36 (PAR-60).

Attack-trigger P/T match, mass keyword strip, end-step exile+token —
hand-authored in `game/ability_catalogue/entries_019.py` on existing
primitives (`grant_until` + `pt_cda`/`remove_keyword`, `exile_target_graveyard`).
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.ability_catalogue import _REGISTRY, is_registered
from mtg_analyzer.game.effect_binder import bind_ability
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone

WAVE36 = ["Tanazir Quandrix", "Arcane Lighthouse", "Quintorius, Loremaster"]


@pytest.mark.parametrize("name", WAVE36)
def test_registered_and_binds(name):
    assert is_registered(name)
    specs = _REGISTRY[name.lower()]()
    assert specs
    src = GameObject(card=Card(id="x", name=name, type_line="Creature — Elder Dragon",
                              is_creature=True, power=5, toughness=5),
                     owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    for s in specs:
        s.validate()
        bind_ability(s, src)


def test_tanazir_attack_grant_matches_base_pt_to_source():
    from mtg_analyzer.game.effect_binder import build_effects
    from mtg_analyzer.game.effects import GameContext
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_hand=0, starting_life=20)
    p1 = eng.state.active_player
    tan = GameObject(card=Card(id="tq", name="Tanazir Quandrix",
                              type_line="Creature — Elder Dragon", is_creature=True,
                              power=6, toughness=6),
                     owner_id=p1.id, zone=Zone.BATTLEFIELD)
    tan.controller_id = p1.id
    eng.state.add_to_battlefield(tan)
    bear = GameObject(card=Card(id="b", name="Bear", type_line="Creature — Bear",
                               is_creature=True, power=2, toughness=2),
                      owner_id=p1.id, zone=Zone.BATTLEFIELD)
    bear.controller_id = p1.id
    eng.state.add_to_battlefield(bear)

    atk_spec = next(s for s in _REGISTRY["tanazir quandrix"]()
                    if s.trigger and str(s.trigger["event"]) == "ATTACKS")
    effs = build_effects(atk_spec.effects, tan)
    ctx = GameContext(state=eng.state, engine=eng.rules)
    for e in effs:
        e.apply(ctx, [])
    eng.recompute_continuous_effects()
    assert (bear.power, bear.toughness) == (6, 6)
    assert (tan.power, tan.toughness) == (6, 6)   # "other creatures" — Tanazir untouched by itself
