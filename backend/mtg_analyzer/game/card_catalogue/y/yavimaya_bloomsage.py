from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# a few more tractable singletons
# ===========================================================================
# Engine: `ConditionalEffect` gained ``previous_target_power_at_least``
# (Yavimaya Bloomsage).


def _yavimaya_bloomsage() -> list[AbilitySpec]:
    """At the beginning of your end step, put a +1/+1 counter on target
    creature you control. Then if that creature has power 7 or greater, this
    creature becomes prepared."""
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("add_counters", {"target_kind": "creature_you_control",
                                            "kind": "+1/+1", "count": 1}),
                EffectSpec("become_prepared", {},
                           condition={"previous_target_power_at_least": 7}),
            ],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"},
                     "phase_relation": "you"},
        ),
    ]


register("Yavimaya Bloomsage", _yavimaya_bloomsage)
register("Yavimaya Bloomsage // Channel", _yavimaya_bloomsage)
