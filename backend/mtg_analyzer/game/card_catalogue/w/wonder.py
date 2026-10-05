from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _wonder() -> list[AbilitySpec]:
    """As long as this card is in your graveyard and you control an
    Island, creatures you control have flying.

    — Wonder, `_anger`'s blue sibling (MEC-22).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {
                "affects": "creatures_you_control",
                "keywords": ["flying"],
                "active_if": {
                    "kind": "control_count",
                    "selector": "lands_you_control_of_type_island",
                    "min": 1,
                },
                "from_graveyard": True,
            })],
        ),
    ]


register("Wonder", _wonder)
