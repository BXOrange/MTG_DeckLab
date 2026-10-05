from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# Fractal Harness ETB + Ceaseless Conflict board wipe
# ===========================================================================
# Engine: ``permanents_destroyed_this_way`` added to
# `_TOKEN_COUNT_CONTEXT_ACCUMULATORS`.


def _fractal_harness() -> list[AbilitySpec]:
    """When this Equipment enters, create a 0/0 green and blue Fractal
    creature token. Put X +1/+1 counters on it and attach this Equipment to
    it.
    Whenever equipped creature attacks, double the number of +1/+1 counters
    on it.
    Equip {2}"""
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("create_token", {
                    "count": 1, "token_name": "Fractal", "power": 0, "toughness": 0,
                    "colors": ["G", "U"], "subtypes": ["Fractal"],
                    "extra_counters": {"kind": "+1/+1",
                                       "count_from_count_selector": "source_x_paid"},
                }),
                EffectSpec("attach", {"target_kind": "created"}),
            ],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("double_counters_on_target", {"target_kind": "attached_permanent",
                                                      "kind": "+1/+1"})],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "attached_permanent"}},
        ),
    ]


register("Fractal Harness", _fractal_harness)
