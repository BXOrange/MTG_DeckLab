from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _beast_mode() -> list[AbilitySpec]:
    """Teamwork 1 (As an additional cost to cast this spell, you may tap
    any number of creatures you control with total power 1 or more.)
    Target creature gets +2/+2 and gains trample until end of turn. Also
    put a +1/+1 counter on that creature if this spell was cast using
    teamwork.

    — PAR-68. The trailing "if this spell was cast using teamwork" gate is
    a plain `EffectSpec.condition={"teamwork_paid": True}` (PAR-56's own
    condition key) on the counter clause; "that creature" is the pump
    clause's own RULE 115 target read back via `AddCountersEffect.
    previous_subject` (`GameContext.previous_targets`, the same "preceding
    clause's own target" pronoun idiom already used for "tap target
    creature and put a stun counter on it"-shaped bodies) rather than a
    second, independent target of its own.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("pump", {
                    "power": 2, "toughness": 2, "keywords": ["Trample"],
                    "target_kind": "creature",
                }),
                EffectSpec(
                    "add_counters", {"count": 1, "kind": "+1/+1", "previous_subject": True},
                    condition={"teamwork_paid": True},
                ),
            ],
        ),
    ]


register("Beast Mode", _beast_mode)
