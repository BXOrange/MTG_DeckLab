from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _midnight_banshee() -> list[AbilitySpec]:
    """Wither
    At the beginning of your upkeep, put a -1/-1 counter on each nonblack
    creature.

    Wither folds in from the RULE 702 catalogue. Authored: the upkeep
    trigger — an ``add_counters`` mass selector (``"each_creature"``)
    narrowed by ``creature_filter={"without_color": "B"}`` (RULE 105 —
    "nonblack"), the same `matches_object_filter` key the single-target
    branch already honours.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {
                "count": 1, "kind": "-1/-1", "selector": "each_creature",
                "creature_filter": {"without_color": "B"},
            })],
            trigger={"event": "STEP_BEGIN", "filter": {"step": "upkeep"}, "phase_relation": "you"},
        ),
    ]


register("Midnight Banshee", _midnight_banshee)
