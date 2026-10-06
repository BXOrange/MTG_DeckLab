from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# Plumb the Forbidden (sacrifice one or more -> scaled draw/lose)
# ===========================================================================
# New `sacrifice_any_number_draw_lose_scaled` effect — the Eventide's Shadow
# sacrifice-choose + picked-count continuation. Documented simplification:
# "copy this spell for each creature sacrificed" is modeled as its net
# effect (one extra draw + 1 life loss per creature), not real stack copies.


def _plumb_the_forbidden() -> list[AbilitySpec]:
    """As an additional cost to cast this spell, you may sacrifice one or
    more creatures. When you do, copy this spell for each creature
    sacrificed this way. You draw a card and lose 1 life."""
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("sacrifice_any_number_draw_lose_scaled", {})],
        ),
    ]


register("Plumb the Forbidden", _plumb_the_forbidden)
