from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _thalisse_reverent_medium() -> list[AbilitySpec]:
    """At the beginning of each end step, create X 1/1 white Spirit creature tokens with flying, where X is the number of tokens you created this turn.

    — Thalisse, Reverent Medium. An unscoped end-step trigger (every player's end step, no ``phase_relation``)
    whose count is the new `tokens_you_created_this_turn` selector (token entries per controller this turn).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "power": 1, "toughness": 1, "colors": ["W"], "subtypes": ["Spirit"], "keywords": ["flying"],
                "token_name": "Spirit", "count_selector": "tokens_you_created_this_turn",
            })],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"}},
        )
    ]


register("Thalisse, Reverent Medium", _thalisse_reverent_medium)
