from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _burning_curiosity() -> list[AbilitySpec]:
    """As an additional cost to cast this spell, you may blight 1. (You may
    put a -1/-1 counter on a creature you control.)
    Exile the top two cards of your library. If this spell's additional cost
    was paid, exile the top three cards instead. Until the end of your next
    turn, you may play those cards.

    Authored: the optional ``blight 1`` additional cost
    (`additional_cost={"blight": 1}` + ``additional_cost_optional``) and an
    ``impulsive_draw`` whose count is overridden 2 -> 3 by the new
    ``count_if_additional_cost_paid`` param (RULE 614 "instead", gated on
    `GameObject.additional_cost_paid`). "Until end of your next turn" is
    `impulsive_draw`'s default window.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("impulsive_draw", {"count": 2, "count_if_additional_cost_paid": 3})],
            additional_cost={"blight": 1},
            additional_cost_optional=True,
        )
    ]


register("Burning Curiosity", _burning_curiosity)
