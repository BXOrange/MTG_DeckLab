from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _wrenns_resolve() -> list[AbilitySpec]:
    """Exile the top two cards of your library. Until the end of your
    next turn, you may play those cards.

    — Imodane deck batch. The shipped `impulsive_draw`, count=2.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("impulsive_draw", {"count": 2})],
        ),
    ]


register("Wrenn's Resolve", _wrenns_resolve)
