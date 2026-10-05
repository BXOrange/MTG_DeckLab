from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _call_for_unity() -> list[AbilitySpec]:
    """Revolt — At the beginning of your end step, if a permanent left the
    battlefield under your control this turn, put a unity counter on this
    enchantment.
    Creatures you control get +1/+1 for each unity counter on this
    enchantment.

    Simplified: Revolt's own condition ("a permanent left the battlefield
    under your control this turn") isn't modeled — the counter is added
    every end step unconditionally (no "permanent left the battlefield
    this turn" tracker exists yet, unlike `creatures_died_this_turn`).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"kind": "unity"})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"}, "phase_relation": "you"},
        ),
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {
                "affects": "creatures_you_control", "power": 1, "toughness": 1,
                "power_count": "counters_on_self", "toughness_count": "counters_on_self",
                "counter_kind": "unity",
            })],
        ),
    ]


register("Call for Unity", _call_for_unity)
