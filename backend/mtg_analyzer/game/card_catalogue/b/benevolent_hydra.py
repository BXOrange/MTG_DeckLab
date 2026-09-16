from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _benevolent_hydra() -> list[AbilitySpec]:
    """This creature enters with X +1/+1 counters on it.
    If one or more +1/+1 counters would be put on another creature you
    control, that many plus one +1/+1 counters are put on it instead.
    {T}, Remove a +1/+1 counter from this creature: Put a +1/+1 counter on
    another target creature you control.

    Documented simplification: the "another" exclusion on the replacement
    (Benevolent Hydra itself also getting the +1 when counters land on it)
    isn't expressible on the `double_counters` recipient scope — a minor
    over-application."""
    return [
        AbilitySpec(
            "replacement",
            [EffectSpec("double_counters", {
                "kind": "+1/+1", "plus": 1, "recipient": "creature_you_control",
            })],
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("add_counters", {"target_kind": "other_creature_you_control",
                                         "kind": "+1/+1", "count": 1})],
            cost={"taps_self": True, "remove_counters": ["+1/+1", 1]},
        ),
    ]


register("Benevolent Hydra", _benevolent_hydra)
