"""Secrets of Strixhaven — playability batch, wave 35 (PAR-60).

Vanishing Verse (new ``monocolored_permanent`` target kind) + two
manland/token singletons, hand-authored in
`game/ability_catalogue/entries_019.py`.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.ability_catalogue import _REGISTRY, is_registered
from mtg_analyzer.game.effect_binder import bind_ability
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.targeting import ALLOWED_TARGET_KINDS, TargetSpec, legal_targets
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone

WAVE35 = ["Vanishing Verse", "Restless Spire", "Determined Iteration"]


@pytest.mark.parametrize("name", WAVE35)
def test_registered_and_binds(name):
    assert is_registered(name)
    specs = _REGISTRY[name.lower()]()
    assert specs
    src = GameObject(card=Card(id="x", name=name, type_line="Land"),
                     owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    for s in specs:
        s.validate()
        bind_ability(s, src)


def test_monocolored_permanent_target_kind():
    assert "monocolored_permanent" in ALLOWED_TARGET_KINDS
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_hand=0, starting_life=20)
    p1 = eng.state.active_player

    def mk(name, ci):
        o = GameObject(card=Card(id=name, name=name, type_line="Creature — Bear",
                                 is_creature=True, color_identity=list(ci)),
                       owner_id=p1.id, zone=Zone.BATTLEFIELD)
        o.controller_id = p1.id
        eng.state.add_to_battlefield(o)
        return o

    mk("Mono", ["W"])
    mk("Gold", ["W", "B"])
    mk("Colorless", [])
    eng.recompute_continuous_effects()
    names = {t["name"] for t in
             legal_targets(eng.state, p1.id, TargetSpec(kind="monocolored_permanent"))}
    assert names == {"Mono"}


def test_restless_spire_animation_shape():
    spec = _REGISTRY["restless spire"]()[0]
    assert spec.ability_kind == "activated"
    types = {e.params["static"]["type"] for e in spec.effects}
    assert types == {"type_change", "grant_keyword"}
