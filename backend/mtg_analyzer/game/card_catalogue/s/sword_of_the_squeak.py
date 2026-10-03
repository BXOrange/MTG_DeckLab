from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _sword_of_the_squeak() -> list[AbilitySpec]:
    """Equipped creature gets +1/+1 for each creature you control with base power or toughness 1.
    Whenever a Hamster, Mouse, Rat, or Squirrel you control enters, you may attach this Equipment to that creature.
    Equip {2}
    """
    return [
        AbilitySpec(
            'keyword',
            [
            ],
            keyword={'name': 'equip', 'cost': '{2}'},
        ),
        AbilitySpec(
            'static',
            [
                EffectSpec('anthem', {'affects': 'attached_permanent',
                            'power': 1,
                            'toughness': 1,
                            'power_count': {'zone': 'battlefield',
                                            'of': 'you',
                                            'filter': {'card_type': 'creature',
                                                       'any_of': [{'base_power': 1},
                                                                  {'base_toughness': 1}]}},
                            'toughness_count': {'zone': 'battlefield',
                                                'of': 'you',
                                                'filter': {'card_type': 'creature',
                                                           'any_of': [{'base_power': 1},
                                                                      {'base_toughness': 1}]}}}),
            ],
        ),
        AbilitySpec(
            'triggered',
            [
                EffectSpec('trigger_subject_referent', {'effects': [{'type': 'attach', 'params': {}}]}),
            ],
            optional=True,
            trigger={'event': 'ENTERS_BATTLEFIELD',
                     'condition': {'subject': 'group',
                                   'controller': 'you',
                                   'subtypes': ['hamster', 'mouse', 'rat', 'squirrel']}},
        ),
    ]


register('Sword of the Squeak', _sword_of_the_squeak)
