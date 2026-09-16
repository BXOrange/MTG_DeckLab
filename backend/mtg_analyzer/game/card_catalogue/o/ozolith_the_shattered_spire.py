from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# the "that many plus one +1/+1 counters" replacement (Hardened
# Scales family) + Kinetic Ooze's X-tiered ETB
# ===========================================================================
# All on existing primitives: the `double_counters` replacement's ``plus``
# param, and `EffectSpec.condition`'s ``source_x_paid_at_least`` key.


def _ozolith_the_shattered_spire() -> list[AbilitySpec]:
    """If one or more +1/+1 counters would be put on an artifact or creature
    you control, that many plus one +1/+1 counters are put on it instead.
    {1}{G}, {T}: Put a +1/+1 counter on target artifact or creature you
    control. Activate only as a sorcery.
    Cycling {2}

    Documented simplification: "an artifact or creature you control" is
    modeled as ``recipient="permanent_you_control"`` — a noncreature
    nonartifact permanent you control (a land, an enchantment) would also
    get the +1 here, a rare corner."""
    return [
        AbilitySpec(
            "replacement",
            [EffectSpec("double_counters", {
                "kind": "+1/+1", "plus": 1, "recipient": "permanent_you_control",
            })],
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("add_counters", {"target_kind": "artifact_or_creature_you_control",
                                            "kind": "+1/+1", "count": 1}),
                EffectSpec("sorcery_speed_marker", {}),
            ],
            cost={"mana": "{1}{G}", "taps_self": True},
        ),
    ]


register("Ozolith, the Shattered Spire", _ozolith_the_shattered_spire)
