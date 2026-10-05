from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# Augusta, Order Returned (each-player graveyard exile payoff) —
# PAR-60
# ===========================================================================
# New `each_player_exile_from_graveyard_then_counters` effect: one atomic
# effect over a shared "target attacking creature" (the
# `CounterUntapGrantKeywordEffect` "don't double-prompt" idiom). Documented
# simplification: each player's exile is auto-picked (oldest graveyard card)
# rather than an interactive per-player choice.


def _augusta_order_returned() -> list[AbilitySpec]:
    """Flying, vigilance (fold in from the RULE 702 catalogue).
    Whenever Augusta attacks, each player exiles a card from their
    graveyard. When one or more nonland cards are exiled this way, put that
    many +1/+1 counters on target attacking creature."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("each_player_exile_from_graveyard_then_counters", {})],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
        ),
    ]


register("Augusta, Order Returned", _augusta_order_returned)
