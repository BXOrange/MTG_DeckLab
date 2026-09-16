from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _valor() -> list[AbilitySpec]:
    """As long as this card is in your graveyard and you control a
    Plains, creatures you control have first strike.

    — Valor, `_anger`'s white sibling (MEC-22).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {
                "affects": "creatures_you_control",
                "keywords": ["first strike"],
                "active_if": {
                    "kind": "control_count",
                    "selector": "lands_you_control_of_type_plains",
                    "min": 1,
                },
                "from_graveyard": True,
            })],
        ),
    ]


register("Valor", _valor)
