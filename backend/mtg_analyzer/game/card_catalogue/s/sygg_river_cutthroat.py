from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _sygg_river_cutthroat() -> list[AbilitySpec]:
    """At the beginning of each end step, if an opponent lost 3 or more life
    this turn, you may draw a card. (Damage causes loss of life.)

    — PLAY-ALL Step 2 (yshtola). Bloodchief Ascension's first trigger with a
    draw as the body: STEP_BEGIN "end" (each player's), RULE 603.4's
    intervening-if as ``active_if`` (`opponent_lost_life_this_turn`).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={
                "event": EventType.STEP_BEGIN, "filter": {"step": "end"},
                "active_if": {"kind": "opponent_lost_life_this_turn", "min": 3},
            },
            optional=True,
        ),
    ]


register("Sygg, River Cutthroat", _sygg_river_cutthroat)
