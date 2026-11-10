from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _live_long_and_prosper() -> list[AbilitySpec]:
    """This spell can't be countered.
    Double your life total. Draw cards equal to the number of cards in your hand. You have no maximum hand size until your next turn.

    RULE 119.1: doubling is gaining life equal to the current total.
    RULE 402.2 / 611.2: the hand-size lift is a floating continuous effect
    that ends when your next turn begins.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("cant_be_countered", {}),
                EffectSpec("gain_life", {"count_selector": "your_life_total"}),
                EffectSpec("draw", {"count": {"kind": "resource", "resource": "hand_size", "of": "you"}}),
                EffectSpec("grant_until", {
                    "static": {"type": "no_max_hand_size", "params": {"affects": "you"}},
                    "duration": "your_next_turn", "target_kind": None,
                }),
            ],
        ),
    ]


register("Live Long and Prosper", _live_long_and_prosper)
