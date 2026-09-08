"""Secrets of Strixhaven — playability batch, wave 40 (PAR-60).

The "that many plus one +1/+1 counters" replacement (Hardened Scales family)
+ Kinetic Ooze's X-tiered ETB, hand-authored in
`game/ability_catalogue/commander_cards.py` on existing primitives (the
`double_counters` replacement's ``plus`` param; `EffectSpec.condition`'s
``source_x_paid_at_least``).
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.ability_catalogue import _REGISTRY, is_registered
from mtg_analyzer.game.binding.core import bind_ability, bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone

WAVE40 = ["Ozolith, the Shattered Spire", "Benevolent Hydra", "Kinetic Ooze"]


@pytest.mark.parametrize("name", WAVE40)
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


def _eng():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_hand=0, starting_life=20)
    return eng, eng.state.active_player


def _bf(eng, pid, name, tl, **kw):
    o = GameObject(card=Card(id=name.replace(" ", "").replace(",", ""), name=name,
                             type_line=tl, **kw), owner_id=pid, zone=Zone.BATTLEFIELD)
    o.controller_id = pid
    eng.state.add_to_battlefield(o)
    return o


def test_ozolith_adds_one_to_every_counter_placement():
    eng, p1 = _eng()
    oz = _bf(eng, p1.id, "Ozolith, the Shattered Spire", "Legendary Artifact")
    bind_from_catalogue(oz)
    bear = _bf(eng, p1.id, "Bear", "Creature — Bear", is_creature=True, power=2, toughness=2)
    eng.rules.add_counters(bear, 2, "+1/+1")
    assert bear.counters.get("+1/+1") == 3   # 2 + 1


def test_benevolent_hydra_plus_one_for_your_creatures():
    eng, p1 = _eng()
    hydra = _bf(eng, p1.id, "Benevolent Hydra", "Creature — Hydra", is_creature=True,
                power=0, toughness=0)
    bind_from_catalogue(hydra)
    ally = _bf(eng, p1.id, "Ally", "Creature — Elf", is_creature=True, power=1, toughness=1)
    eng.rules.add_counters(ally, 1, "+1/+1")
    assert ally.counters.get("+1/+1") == 2   # 1 + 1


def test_kinetic_ooze_x_tiers():
    spec = _REGISTRY["kinetic ooze"]()[0]
    conds = [getattr(e, "condition", None) for e in spec.effects]
    assert {"source_x_paid_at_least": 5} in conds
    assert {"source_x_paid_at_least": 10} in conds
