from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _relic_retriever() -> list[AbilitySpec]:
    """First strike
    At the beginning of each end step, if a card left your graveyard this
    turn, create a Treasure token."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {"count": 1, "token_name": "Treasure"})],
            trigger={
                "event": EventType.STEP_BEGIN, "filter": {"step": "end"},
                "active_if": {"kind": "card_left_graveyard_this_turn"},
            },
        ),
    ]


register("Relic Retriever", _relic_retriever)
