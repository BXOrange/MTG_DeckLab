from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _cultural_exchange() -> list[AbilitySpec]:
    """Choose any number of creatures target player controls. Choose the
    same number of creatures another target player controls. Those players
    exchange control of those creatures. (This effect lasts indefinitely.)

    — See `CulturalExchangeEffect`'s own docstring for the two chained
    interactive rounds and its documented "same number" simplification.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("cultural_exchange", {})],
        ),
    ]


register("Cultural Exchange", _cultural_exchange)
