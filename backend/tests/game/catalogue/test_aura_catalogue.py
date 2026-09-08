"""Catalogue validation for Aura-focused card entries."""

from __future__ import annotations

import pytest

from mtg_analyzer.game.ability_catalogue import _REGISTRY, is_registered
from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone

AURA_CARDS = [
    "Kor Spiritdancer", "Sage's Reverie", "Eidolon of Countless Battles",
    "Angelic Destiny", "Eldrazi Conscription", "Shielded by Faith",
    "Sheltered by Ghosts", "Chains of Custody", "Darksteel Mutation",
    "Fallen Ideal", "Raffine's Guidance", "Ajani's Chosen",
]


@pytest.mark.parametrize("name", AURA_CARDS)
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
    from mtg_analyzer.game.binding.core import bind_ability
    for s in specs:
        bind_ability(s, src)

