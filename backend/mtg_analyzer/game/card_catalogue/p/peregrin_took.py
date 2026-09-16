from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _peregrin_took() -> list[AbilitySpec]:
    """If one or more tokens would be created under your control, those
    tokens plus an additional Food token are created instead.
    Sacrifice three Foods: Draw a card.
    """
    return [
        AbilitySpec(
            "replacement",
            [EffectSpec("additional_named_token", {"token_name": "Food"})],
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("draw", {"count": 1})],
            cost={"sacrifice_count": (3, "food")},
        ),
    ]


register("Peregrin Took", _peregrin_took)
