from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _blossoming_bogbeast() -> list[AbilitySpec]:
    """Whenever this creature attacks, you gain 2 life. Then creatures you
    control gain trample and get +X/+X until end of turn, where X is the
    amount of life you gained this turn.

    ``gain_life`` runs first so ``life_gained_this_turn`` already includes the
    2 by the time the group pump reads it."""
    BOGBEAST_LIFEGAIN = 2
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("gain_life", {"amount": BOGBEAST_LIFEGAIN}),
                EffectSpec("pump", {
                    "selector": "creatures_you_control", "keywords": ["trample"],
                    "amount_from_count_selector": "life_gained_this_turn",
                }),
            ],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
        ),
    ]


register("Blossoming Bogbeast", _blossoming_bogbeast)
