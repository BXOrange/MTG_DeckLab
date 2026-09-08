"""Shared synthetic-card factories for service tests."""

from mtg_analyzer.models.cards.card import Card


def forest(name: str = "Forest") -> Card:
    return Card(id=name, name=name, type_line="Basic Land — Forest", is_land=True)


def commander() -> Card:
    return Card(
        id="Test Commander",
        name="Test Commander",
        type_line="Legendary Creature — Elf",
        mana_cost_string="{1}{G}",
        converted_mana_cost=2,
        is_creature=True,
        power=1,
        toughness=1,
        color_identity={"G"},
    )


def cheap_creature(name: str = "Test Spell") -> Card:
    return Card(
        id=name,
        name=name,
        type_line="Creature — Elf",
        mana_cost_string="{G}",
        converted_mana_cost=1,
        is_creature=True,
        power=1,
        toughness=1,
        color_identity={"G"},
    )
