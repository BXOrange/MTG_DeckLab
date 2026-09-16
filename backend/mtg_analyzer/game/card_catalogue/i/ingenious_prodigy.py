from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _ingenious_prodigy() -> list[AbilitySpec]:
    """Skulk
    This creature enters with X +1/+1 counters on it.
    At the beginning of your upkeep, if this creature has one or more +1/+1
    counters on it, you may remove a +1/+1 counter from it. If you do, draw a
    card."""
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("remove_counters", {}),
                EffectSpec("draw", {"count": 1}),
            ],
            trigger={
                "event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"},
                "phase_relation": "you",
                "active_if": {"kind": "source_counters", "counter": "+1/+1", "min": 1},
            },
            optional=True,
        ),
    ]


register("Ingenious Prodigy", _ingenious_prodigy)
