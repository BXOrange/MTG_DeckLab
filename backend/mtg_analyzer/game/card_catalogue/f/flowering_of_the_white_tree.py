from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _flowering_of_the_white_tree() -> list[AbilitySpec]:
    """Legendary creatures you control get +2/+1 and have ward {1}.
    Nonlegendary creatures you control get +1/+1.

    Simplified: the granted "have ward {1}" isn't modeled — the layer-6
    keyword-grant mechanism only carries flag keywords today (ward is
    parametric, a real pre-existing gap: `parser/oracle/catalogue/
    static_handlers._flag_keywords` fails closed on any granted parametric
    keyword). Both anthems (+2/+1 legendary / +1/+1 nonlegendary) are fully
    modeled.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {"affects": "legendary_creatures_you_control", "power": 2, "toughness": 1})],
        ),
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {"affects": "nonlegendary_creatures_you_control", "power": 1, "toughness": 1})],
        ),
    ]


register("Flowering of the White Tree", _flowering_of_the_white_tree)
