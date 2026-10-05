from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _war_room() -> list[AbilitySpec]:
    """{T}: Add {C}.
    {3}, {T}, Pay life equal to the number of colors in your commanders' color identity: Draw a card.
    """
    # The {T}: Add {C} mana ability isn't a spec — `mana_abilities` derives it
    # from the oracle text (Encroaching Wastes' sibling idiom). The life amount
    # is `costs.PAY_LIFE_COMMANDER_COLORS`, resolved at payment (RULE 903.4).
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("draw", {"count": 1})],
            cost={"mana": "{3}", "taps_self": True, "pay_life": "commander_colors"},
        )
    ]


register("War Room", _war_room)
