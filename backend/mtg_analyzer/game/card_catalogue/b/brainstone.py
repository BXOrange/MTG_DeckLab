from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _brainstone() -> list[AbilitySpec]:
    """{2}, {T}, Sacrifice this artifact: Draw three cards, then put two cards from your hand on top of your library in any order.

    — PLAY-ALL (Miracle Worker). Brainstorm's `draw` + `put_hand_cards_on_top` behind the activation cost.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("draw", {"count": 3}), EffectSpec("put_hand_cards_on_top", {"count": 2})],
            cost={"mana": "{2}", "taps_self": True, "sacrifice": "self"},
        ),
    ]


register("Brainstone", _brainstone)
