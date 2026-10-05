from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _martyrs_cause() -> list[AbilitySpec]:
    """Sacrifice a creature: The next time a source of your choice would
    deal damage to any target this turn, prevent that damage.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("request_prevent_damage_source", {
                "target_kind": "any", "amount": "all",
            })],
            cost={"text": "Sacrifice a creature"},
        ),
    ]


register("Martyr's Cause", _martyrs_cause)
