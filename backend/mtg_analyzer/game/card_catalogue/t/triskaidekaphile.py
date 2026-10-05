from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _triskaidekaphile() -> list[AbilitySpec]:
    """You have no maximum hand size.
    At the beginning of your upkeep, if you have exactly thirteen cards in your hand, you win the game.
    {3}{U}: Draw a card.

    — Peace Offering deck batch. The static and the draw are the parser's own claims; "exactly thirteen" is
    `cards_in_hand_at_least` and `cards_in_hand_at_most` both at 13, gating `win_game` (Simic Ascendancy's
    upkeep-win shape).
    """
    return [
        AbilitySpec("static", [EffectSpec("no_max_hand_size", {"affects": "you"})]),
        AbilitySpec(
            "triggered",
            [EffectSpec("win_game", {}, condition={"kind": "all", "conditions": [
                {"kind": "cards_in_hand_at_least", "amount": 13},
                {"kind": "cards_in_hand_at_most", "amount": 13},
            ]})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"}, "phase_relation": "you"},
        ),
        AbilitySpec("activated", [EffectSpec("draw", {"count": 1})], cost={"text": "{3}{u}"}),
    ]


register("Triskaidekaphile", _triskaidekaphile)
