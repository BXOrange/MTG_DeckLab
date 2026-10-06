from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _irma_part_time_mutant() -> list[AbilitySpec]:
    """Copy an optional other controlled creature while retaining the combat trigger, then grow."""
    return [AbilitySpec("triggered", [
        EffectSpec("become_copy_permanent", {"target_kind": "other_creature_you_control", "optional": True,
            "retain_trigger_index": 0, "set_name": "Irma, Part-Time Mutant"}),
        EffectSpec("add_counters", {"kind": "+1/+1", "count": 1}),
    ], trigger={"event": "STEP_BEGIN", "filter": {"step": "begin_combat"}, "phase_relation": "you"})]


register('Irma, Part-Time Mutant', _irma_part_time_mutant)
