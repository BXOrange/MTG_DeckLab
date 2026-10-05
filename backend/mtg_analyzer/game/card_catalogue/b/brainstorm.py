from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _brainstorm() -> list[AbilitySpec]:
    """Draw three cards, then put two cards from your hand on top of your
    library in any order.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("draw", {"count": 3}),
                EffectSpec("put_hand_cards_on_top", {"count": 2}),
            ],
        )
    ]


register("Brainstorm", _brainstorm)
