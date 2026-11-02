
from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _windswift_slice() -> list[AbilitySpec]:
    "Target creature you control deals damage equal to its power to target creature you don't control. Create a number of 1/1 green Elf Warrior creature tokens equal to the amount of excess damage dealt this way."
    return [
        AbilitySpec("spell_effect", [
            EffectSpec("damage_equal_to_power", {"dealer_kind": "creature_you_control", "target_kind": "creature_you_dont_control"}),
            EffectSpec("create_token", {"count": {"kind": "this_way", "tally": "excess_damage_this_way"},
                "token_name": "Elf Warrior", "power": 1, "toughness": 1, "colors": ["G"], "subtypes": ["Elf", "Warrior"]}),
        ]),
    ]


register('Windswift Slice', _windswift_slice)
