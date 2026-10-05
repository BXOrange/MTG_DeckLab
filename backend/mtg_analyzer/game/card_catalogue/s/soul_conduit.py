from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _soul_conduit() -> list[AbilitySpec]:
    """{6}, {T}: Two target players exchange life totals.

    — MEC-43 round 2. The new `ExchangeLifeTotalsEffect` — a genuinely new
    one-shot, since every other life effect in this engine is a single-
    player delta.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("exchange_life_totals", {})],
            cost={"text": "{6}", "taps_self": True},
        )
    ]


register("Soul Conduit", _soul_conduit)
