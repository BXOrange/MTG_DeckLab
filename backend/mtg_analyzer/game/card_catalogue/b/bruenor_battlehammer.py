from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _bruenor_battlehammer() -> list[AbilitySpec]:
    """Each creature you control gets +2/+0 for each Equipment attached to it.
    You may pay {0} rather than pay the equip cost of the first equip
    ability you activate each turn.

    — Bruenor Battlehammer. The cost-reduction clause isn't modeled (the
    engine's cost-reduction static only scopes to spells being cast, not
    activated-ability costs) — a documented gap.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {
                "affects": "creatures_you_control", "power": 2, "toughness": 0,
                "power_count": "equipment_attached_to_self",
            })],
        )
    ]


register("Bruenor Battlehammer", _bruenor_battlehammer)
