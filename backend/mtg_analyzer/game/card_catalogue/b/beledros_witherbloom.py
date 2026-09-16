from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _beledros_witherbloom() -> list[AbilitySpec]:
    """Flying
    At the beginning of each upkeep, create a 1/1 black and green Pest
    creature token with "When this token dies, you gain 1 life."
    Pay 10 life: Untap all lands you control. Activate only once each turn."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 1, "token_name": "Pest", "power": 1, "toughness": 1,
                "colors": ["B", "G"], "subtypes": ["Pest"], "token_dies_gain_life": 1,
            })],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"}},
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("tap", {"selector": "lands_you_control", "untap": True}),
                EffectSpec("once_per_turn_marker", {}),
            ],
            cost={"text": "Pay 10 life"},
        ),
    ]


register("Beledros Witherbloom", _beledros_witherbloom)
