from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# mixed singletons
# ===========================================================================
# Engine: binder predicate ``defender_is_you`` (Mangara / Tomik).


def _pest_infestation() -> list[AbilitySpec]:
    """Destroy up to X target artifacts and/or enchantments. Create twice X
    1/1 black and green Pest creature tokens with "When this token dies, you
    gain 1 life."""
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("destroy", {
                    "target_kind": "artifact_or_enchantment", "count": "x", "count_max": "x",
                    "optional": True,
                }),
                EffectSpec("create_token", {
                    "x_multiplier": 2, "token_name": "Pest",
                    "power": 1, "toughness": 1, "colors": ["B", "G"], "subtypes": ["Pest"],
                    "token_dies_gain_life": 1,
                }),
            ],
        ),
    ]


register("Pest Infestation", _pest_infestation)
