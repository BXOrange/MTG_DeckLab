from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _conspiracy_theorist() -> list[AbilitySpec]:
    """Whenever this creature attacks, you may pay {1} and discard a card. If
    you do, draw a card.
    Whenever you discard one or more nonland cards, you may exile one of them
    from your graveyard. If you do, you may cast it this turn."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("pay_cost_then", {
                "cost": "{1}",
                "effects": [
                    {"type": "discard", "params": {"count": 1}},
                    {"type": "draw", "params": {"count": 1}},
                ],
            })],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("exile_triggering_discard_may_play_this_turn", {})],
            trigger={"event": EventType.DISCARD_CARD, "condition": {"subject": "you"}},
        ),
    ]


register("Conspiracy Theorist", _conspiracy_theorist)
