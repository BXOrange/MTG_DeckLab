from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _silkguard() -> list[AbilitySpec]:
    """Put a +1/+1 counter on each of up to X target creatures you control.
    Auras, Equipment, and modified creatures you control gain hexproof until
    end of turn.

    Documented simplification: the second clause is modeled as "creatures
    you control gain hexproof until end of turn" — the Aura/Equipment and
    "modified" narrowing isn't expressible on the mass-pump selector."""
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("add_counters", {
                    "target_kind": "creature_you_control", "count": "x", "count_max": "x",
                    "kind": "+1/+1",
                }),
                EffectSpec("pump", {
                    "selector": "creatures_you_control", "keywords": ["hexproof"],
                }),
            ],
        ),
    ]


register("Silkguard", _silkguard)
