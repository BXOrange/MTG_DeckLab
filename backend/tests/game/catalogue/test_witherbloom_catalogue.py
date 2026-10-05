"""Catalogue validation for Witherbloom-focused card entries."""

from __future__ import annotations

import pytest

from mtg_analyzer.game.card_registry import _REGISTRY, is_registered
from mtg_analyzer.game.binding.core import bind_ability, build_effects
from mtg_analyzer.game.effects.core import GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.spec import EffectSpec

WITHERBLOOM_CARDS = [
    "Mortality Spear", "Defiling Daemogoth", "Witch of the Moors",
    "Blossoming Bogbeast", "Eccentric Pestfinder", "Merchant of Venom",
    "Mazirek, Kraul Death Priest", "Smothering Abomination",
    "Dina, Soul Steeper", "Dina, Essence Brewer",
]


@pytest.mark.parametrize("name", WITHERBLOOM_CARDS)
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

