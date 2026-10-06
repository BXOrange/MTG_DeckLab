from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _telling_time() -> list[AbilitySpec]:
    """Look at the top three cards of your library. Put one of those cards into your hand, one on top of your library, and one on the bottom of your library.

    — PLAY-ALL (Miracle Worker). `look_top_select` (one card to hand) whose rest goes to the new ``library_top_bottom`` destination: ordered
    by the player, the first card goes on top and the other to the bottom.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("look_top_select", {
                "count": 3, "select_count": 1, "rest_destination": "library_top_bottom", "rest_order": "any",
            })],
        ),
    ]


register("Telling Time", _telling_time)
