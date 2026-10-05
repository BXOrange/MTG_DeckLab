from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _psychic_transfer() -> list[AbilitySpec]:
    """If the difference between your life total and target player's life
    total is 5 or less, exchange life totals with that player.

    — The new `ExchangeLifeTotalsEffect.life_difference_at_most` pre-effect
    numeric gate.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("exchange_life_totals", {
                "target_kind": "player", "life_difference_at_most": 5,
            })],
        ),
    ]


register("Psychic Transfer", _psychic_transfer)
