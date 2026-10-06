from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _level_up() -> list[AbilitySpec]:
    """The enchanted creature owns the attack trigger (RULE 109.5), doubling counters before checking power."""
    return [
        AbilitySpec("triggered", [EffectSpec("add_counters", {"count": 1, "target_kind": "attached_permanent"})],
                    trigger={"event": "ENTERS_BATTLEFIELD", "condition": {"subject": "self"}}),
        AbilitySpec("static", [EffectSpec("grant_triggered_ability", {
            "affects": "attached_permanent", "trigger_event": "ATTACKS", "grant_effects": [
                {"type": "double_counters_on_target", "params": {"kind": "+1/+1", "mode": "previous_subject"}},
                {"type": "draw", "params": {"count": 1}, "condition": {"kind": "power", "of": "source", "min": 10}},
            ],
        })]),
    ]


register('Level Up', _level_up)
