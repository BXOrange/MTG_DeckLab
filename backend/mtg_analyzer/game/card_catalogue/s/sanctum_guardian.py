from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _sanctum_guardian() -> list[AbilitySpec]:
    """Sacrifice this creature: The next time a source of your choice would
    deal damage to any target this turn, prevent that damage.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("request_prevent_damage_source", {
                "target_kind": "any", "amount": "all",
            })],
            cost={"text": "Sacrifice ~"},
        ),
    ]


register("Sanctum Guardian", _sanctum_guardian)
