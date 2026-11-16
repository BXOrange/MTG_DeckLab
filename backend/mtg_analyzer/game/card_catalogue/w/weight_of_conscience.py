
from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _weight_of_conscience() -> list[AbilitySpec]:
    "Enchant creature\nEnchanted creature can't attack.\nTap two untapped creatures you control that share a creature type: Exile enchanted creature."
    return [
        AbilitySpec(
            'static',
            [EffectSpec('grant_keyword', {"keywords": ['cant_attack'], "affects": 'attached_permanent'})],
            raw_text="enchanted creature can't attack.",
        ),
        AbilitySpec('activated', [EffectSpec('exile', {'target_kind': 'attached_permanent'})],
                    cost={'tap_others': [2, 'creature'], 'tap_shared_creature_type': True}),
    ]


register('Weight of Conscience', _weight_of_conscience)
