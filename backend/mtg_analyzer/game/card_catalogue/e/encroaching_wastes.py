from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _encroaching_wastes() -> list[AbilitySpec]:
    """{T}: Add {C}.
    {4}, {T}, Sacrifice this land: Destroy target nonbasic land.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("destroy", {"target_kind": "nonbasic_land"})],
            cost={"mana": "{4}", "taps_self": True, "sacrifice": "self"},
        )
    ]


register("Encroaching Wastes", _encroaching_wastes)
