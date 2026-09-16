from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _hedron_field_purists() -> list[AbilitySpec]:
    """Level up {2}{W}
    LEVEL 1-4  1/4
    If a source would deal damage to you or a creature you control,
    prevent 1 of that damage.
    LEVEL 5+  2/5
    If a source would deal damage to you or a creature you control,
    prevent 2 of that damage.

    — Level up itself and the level-banded P/T (1/4 vs. 2/5) are the
    ordinary structural RULE 711 Leveler handling (`Card.is_leveler`,
    independent of catalogue registration, the same way a DFC's transform
    is structural rather than per-card). Only the prevent-damage bands
    needed writing: two `prevent_damage` specs gated by `active_if`'s
    already-shipped `source_counters` kind (RULE 613.6, `game/static_
    conditions.py`), the exact shape already execute-tested synthetically
    in `test_prevent_damage_family.py`.
    """
    return [
        AbilitySpec(
            "replacement",
            [EffectSpec("prevent_damage", {
                "recipient_union": ["controller", {}], "amount": 1,
                "active_if": {"kind": "source_counters", "counter": "level", "min": 1, "max": 4},
            })],
        ),
        AbilitySpec(
            "replacement",
            [EffectSpec("prevent_damage", {
                "recipient_union": ["controller", {}], "amount": 2,
                "active_if": {"kind": "source_counters", "counter": "level", "min": 5},
            })],
        ),
    ]


register("Hedron-Field Purists", _hedron_field_purists)
