from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _deathbringer_regent() -> list[AbilitySpec]:
    """A cast-from-hand entry wipe with a live intervening creature count."""
    gate = {"kind": "all", "conditions": [
        {"kind": "flag", "flag": "was_cast_from_hand"},
        {"kind": "control_count", "min": 5, "selector": {
            "of": "any", "filter": {"creature": True, "not_reference": True},
        }},
    ]}
    return [AbilitySpec("triggered", [EffectSpec("destroy", {
        "selector": "all_other_creatures",
    }, condition=gate)], trigger={
        "event": "ENTERS_BATTLEFIELD", "condition": {"subject": "self"},
        "filter": {"from_zone": "stack"}, "active_if": gate,
    })]


register("Deathbringer Regent", _deathbringer_regent)
