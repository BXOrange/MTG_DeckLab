from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _martial_coup() -> list[AbilitySpec]:
    """Create X 1/1 white Soldier creature tokens. If X is 5 or more,
    destroy all other creatures.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("create_token", {
                    "count": "x", "power": 1, "toughness": 1, "colors": ["W"],
                    "subtypes": ["Soldier"], "token_name": "Soldier",
                }),
                EffectSpec(
                    "destroy", {"selector": "all_creatures", "exclude_created": True},
                    condition={"source_x_paid_at_least": 5},
                ),
            ],
        ),
    ]


register("Martial Coup", _martial_coup)
