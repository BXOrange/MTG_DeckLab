"""Secrets of Strixhaven — playability batch, wave 22 (PAR-60).

Silverquill "Influence": the Aura / enchantments-matter cluster, hand-authored
in `game/ability_catalogue/entries_019.py`. New engine selectors:
``auras_you_control`` (`continuous.count_selector`) and
``auras_attached_to_self`` (`continuous._pt_mod_count`, the Aura sibling of
``equipment_attached_to_self``).
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.ability_catalogue import _REGISTRY, is_registered
from mtg_analyzer.game.effect_binder import build_effects
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone

WAVE22 = [
    "Kor Spiritdancer", "Sage's Reverie", "Eidolon of Countless Battles",
    "Angelic Destiny", "Eldrazi Conscription", "Shielded by Faith",
    "Sheltered by Ghosts", "Chains of Custody", "Darksteel Mutation",
    "Fallen Ideal", "Raffine's Guidance", "Ajani's Chosen",
]


@pytest.mark.parametrize("name", WAVE22)
def test_registered_and_specs_validate(name):
    assert is_registered(name)
    specs = _REGISTRY[name.lower()]()
    assert specs
    for s in specs:
        s.validate()
    # binding must not raise (every EffectSpec.type is a real registry key)
    src = GameObject(card=Card(id="x", name=name, type_line="Enchantment"),
                     owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    from mtg_analyzer.game.effect_binder import bind_ability
    for s in specs:
        bind_ability(s, src)


def _eng_one():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_hand=0, starting_life=20)
    return eng, eng.state.active_player


def _mk(eng, pid, name, tl, **kw):
    o = GameObject(card=Card(id=name.replace(" ", ""), name=name, type_line=tl, **kw),
                   owner_id=pid, zone=Zone.BATTLEFIELD)
    o.controller_id = pid
    eng.state.add_to_battlefield(o)
    return o


def test_kor_spiritdancer_scales_with_attached_auras():
    eng, p1 = _eng_one()
    kor = _mk(eng, p1.id, "Kor Spiritdancer", "Creature — Kor Wizard",
              is_creature=True, power=0, toughness=2)
    kor.static_effects.extend(build_effects(
        [s for spec in _REGISTRY["kor spiritdancer"]() if spec.ability_kind == "static"
         for s in [spec.effects[0]]], kor))
    eng.recompute_continuous_effects()
    assert (kor.power, kor.toughness) == (0, 2)

    for i in range(2):
        aura = _mk(eng, p1.id, f"Aura{i}", "Enchantment — Aura")
        aura.attached_to = kor.instance_id
    eng.recompute_continuous_effects()
    assert (kor.power, kor.toughness) == (4, 6)


def test_sheltered_by_ghosts_buffs_enchanted_creature():
    eng, p1 = _eng_one()
    bear = _mk(eng, p1.id, "Bear", "Creature — Bear", is_creature=True, power=2, toughness=2)
    aura = _mk(eng, p1.id, "Sheltered by Ghosts", "Enchantment — Aura")
    aura.attached_to = bear.instance_id
    static_specs = [e for spec in _REGISTRY["sheltered by ghosts"]()
                    if spec.ability_kind == "static" for e in spec.effects]
    aura.static_effects.extend(build_effects(static_specs, aura))
    eng.recompute_continuous_effects()
    assert (bear.power, bear.toughness) == (3, 2)
    assert "lifelink" in bear.granted_keywords
    assert getattr(bear, "granted_ward_cost", None) == "{2}"


def test_darksteel_mutation_neuters_enchanted_creature():
    eng, p1 = _eng_one()
    dragon = _mk(eng, p1.id, "Big Dragon", "Creature — Dragon",
                 is_creature=True, power=6, toughness=6)
    aura = _mk(eng, p1.id, "Darksteel Mutation", "Enchantment — Aura")
    aura.attached_to = dragon.instance_id
    specs = [e for spec in _REGISTRY["darksteel mutation"]()
             if spec.ability_kind == "static" for e in spec.effects]
    aura.static_effects.extend(build_effects(specs, aura))
    eng.recompute_continuous_effects()
    assert (dragon.power, dragon.toughness) == (0, 1)
    assert dragon.loses_all_abilities
    assert "indestructible" in dragon.granted_keywords
