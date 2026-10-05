from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _valakut_awakening() -> list[AbilitySpec]:
    """Put any number of cards from your hand on the bottom of your
    library, then draw that many cards plus one.

    Simplified: narrowed to "draw a card" — no primitive puts a player-
    chosen number of hand cards on the bottom of the library paired with a
    scaled draw yet (`PutHandCardsOnTopEffect` is a fixed count, to the
    top, with no paired draw).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("draw", {"count": 1})],
        ),
    ]


register("Valakut Awakening", _valakut_awakening)
register("Valakut Awakening // Valakut Stoneforge", _valakut_awakening)
