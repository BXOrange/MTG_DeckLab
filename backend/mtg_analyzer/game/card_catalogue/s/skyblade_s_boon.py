
from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _skyblade_s_boon() -> list[AbilitySpec]:
    "Enchant creature\nEnchanted creature gets +1/+1 and has flying.\n{2}{W}: Return Skyblade's Boon to its owner's hand. Activate only if Skyblade's Boon is on the battlefield or in your graveyard."
    return [
        AbilitySpec(
            'static',
            [EffectSpec('anthem', {"power": 1, "toughness": 1, "affects": 'attached_permanent'}), EffectSpec('grant_keyword', {"affects": 'attached_permanent', "keywords": ['flying']})],
            raw_text='enchanted creature gets +1/+1 and has flying.',
        ),
        AbilitySpec('activated', [EffectSpec('return_to_hand', {'target_kind': None})],
                    cost={'mana': '{2}{W}', 'activation_zones': ['battlefield', 'graveyard']}),
    ]


register("Skyblade's Boon", _skyblade_s_boon)
