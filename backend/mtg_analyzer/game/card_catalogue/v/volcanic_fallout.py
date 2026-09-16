from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _volcanic_fallout() -> list[AbilitySpec]:
    """This spell can't be countered.
    Volcanic Fallout deals 2 damage to each creature and each player.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("cant_be_countered", {}),
                EffectSpec("damage", {"amount": 2, "selector": "each_creature_and_player"}),
            ],
        )
    ]


register("Volcanic Fallout", _volcanic_fallout)
