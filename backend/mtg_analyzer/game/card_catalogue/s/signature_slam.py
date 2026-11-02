
from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _signature_slam() -> list[AbilitySpec]:
    "Put a +1/+1 counter on target creature you control, then each modified creature you control deals damage equal to its power to target creature you don't control. (Equipment, Auras you control, and counters are modifications.)"
    return [
        AbilitySpec("spell_effect", [
            EffectSpec("add_counters", {"amount": 1, "target_kind": "creature_you_control"}),
            EffectSpec("damage_equal_to_power", {"dealer_group": {"zone": "battlefield", "of": "you", "filter": {"card_type": "creature", "modified": True}},
                "target_kind": "creature_you_dont_control"}),
        ]),
    ]


register('Signature Slam', _signature_slam)
