from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _darksteel_mutation() -> list[AbilitySpec]:
    """Enchant creature
    Enchanted creature is an Insect artifact creature with base power and
    toughness 0/1 and has indestructible, and it loses all other abilities,
    card types, and creature types.

    — the Kenrith's Transformation "Elk" template plus an artifact type and
    indestructible. Documented simplification: only creature types are
    replaced (`set_subtypes`) and artifact/creature are added; a prior
    *enchantment* card type isn't stripped (`Card.is_enchantment` reads the
    printed card, not a layer-4 property — the same gap Kenrith's
    Transformation flags)."""
    return [
        AbilitySpec(
            "static",
            [
                EffectSpec("remove_all_abilities", {"affects": "attached_permanent"}),
                EffectSpec("type_change", {
                    "affects": "attached_permanent",
                    "add_types": ["artifact", "creature"],
                    "set_subtypes": ["Insect"], "power": 0, "toughness": 1,
                }),
                EffectSpec("grant_keyword", {
                    "affects": "attached_permanent", "keywords": ["indestructible"],
                }),
            ],
        ),
    ]


register("Darksteel Mutation", _darksteel_mutation)
