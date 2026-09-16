from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _indomitable_archangel() -> list[AbilitySpec]:
    """Flying
    Metalcraft — Artifacts you control have shroud as long as you control
    three or more artifacts.

    — Flying comes from the RULE 702 keyword catalogue.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {
                "affects": "artifacts_you_control", "keywords": ["shroud"],
                "min_count_selector": "artifacts_you_control", "min_count": 3,
            })],
        )
    ]


register("Indomitable Archangel", _indomitable_archangel)
