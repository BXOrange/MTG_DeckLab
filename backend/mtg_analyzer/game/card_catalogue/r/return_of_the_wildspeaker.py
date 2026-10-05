from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _return_of_the_wildspeaker() -> list[AbilitySpec]:
    """Return of the Wildspeaker's two modal, non-Human-only effects."""
    return [
        AbilitySpec(
            "spell_effect", [],
            modes={
                "choose": 1,
                "options": [
                    [EffectSpec("draw", {
                        "amount_from_count_selector":
                        "greatest_non_human_creature_power_you_control",
                    })],
                    [EffectSpec("pump", {
                        "power": 3, "toughness": 3,
                        "selector": "non_human_creatures_you_control",
                    })],
                ],
                "descriptions": [
                    "Draw cards equal to the greatest power among non-Human creatures you control.",
                    "Non-Human creatures you control get +3/+3 until end of turn.",
                ],
            },
        ),
    ]


register("Return of the Wildspeaker", _return_of_the_wildspeaker)
