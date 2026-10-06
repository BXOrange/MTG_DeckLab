from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _high_score() -> list[AbilitySpec]:
    """If one or more +1/+1 counters would be put on a creature you control, that many plus one +1/+1 counters are put on it instead.
    At the beginning of your end step, draw a card if you control a creature with the greatest power among creatures on the battlefield.

    — PLAY-ALL (Turtle Power!). The replacement is the parser's claim (`double_counters` with ``plus`` 1). The end-step draw is an intervening-if on ``controls_greatest_power_creature`` (the controller's best
    creature is at least as powerful as every creature).
    """
    return [
        AbilitySpec("replacement", [EffectSpec("double_counters", {"kind": "+1/+1", "plus": 1, "recipient": "creature_you_control"})]),
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={
                "event": EventType.STEP_BEGIN, "filter": {"step": "end"}, "phase_relation": "you",
                "active_if": {"kind": "controls_greatest_power_creature"},
            },
        ),
    ]


register("High Score", _high_score)
