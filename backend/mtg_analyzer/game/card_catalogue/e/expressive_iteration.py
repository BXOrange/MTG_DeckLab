from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# Expressive Iteration (look 3: hand / bottom / exile-play) — PAR-60
# ===========================================================================
# New `expressive_iteration` effect: two chained `_request_choose_objects`
# picks (hand card, then which of the last two to exile with a this-turn
# play window; the other goes to the bottom).


def _expressive_iteration() -> list[AbilitySpec]:
    """Look at the top three cards of your library. Put one of them into
    your hand, put one of them on the bottom of your library, and exile one
    of them. You may play the exiled card this turn."""
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("expressive_iteration", {})],
        ),
    ]


register("Expressive Iteration", _expressive_iteration)
