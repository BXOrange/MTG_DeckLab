from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _first_responder() -> list[AbilitySpec]:
    """Bounce another chosen creature, then measure its battlefield power."""
    return [AbilitySpec("triggered", [EffectSpec("choose_objects", {
        "action": "return_to_hand", "what": "creature", "exclude_self": True, "optional": True,
        "then_that_many": {"measure": "power", "effects": [{
            "type": "add_counters", "params": {"kind": "+1/+1", "count": "x", "target_kind": None},
        }]},
    })], trigger={"event": "STEP_BEGIN", "filter": {"step": "end"}, "phase_relation": "you"})]


register("First Responder", _first_responder)
