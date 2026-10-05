from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _garruk_cursed_huntsman() -> list[AbilitySpec]:
    """0: Create two 2/2 black and green Wolf creature tokens with "When this token dies, put a loyalty counter on each Garruk you control."
    −3: Destroy target creature. Draw a card.
    −6: You get an emblem with "Creatures you control get +3/+3 and have trample."
    """
    return [
        AbilitySpec(
            'activated',
            [
                EffectSpec('destroy', {'target_kind': 'creature'}),
                EffectSpec('draw', {'count': 1}),
            ],
            cost={'loyalty': -3},
        ),
        AbilitySpec(
            'activated',
            [
                EffectSpec('create_emblem', {'ability': {'ability_kind': 'static',
                                        'effects': [{'type': 'anthem',
                                                     'params': {'power': 3,
                                                                'toughness': 3,
                                                                'affects': 'creatures_you_control'}},
                                                    {'type': 'grant_keyword',
                                                     'params': {'affects': 'creatures_you_control',
                                                                'keywords': ['trample']}}],
                                        'trigger': None,
                                        'cost': None,
                                        'target': None,
                                        'keyword': None,
                                        'modes': None,
                                        'additional_cost': None,
                                        'additional_cost_optional': False,
                                        'conditional_flash': None,
                                        'cast_timing_restriction': None,
                                        'cast_condition': None,
                                        'flash_extra_cost': None,
                                        'free_cast_condition': None,
                                        'optional': False,
                                        'raw_text': 'creatures you control get +3/+3 and have '
                                                    'trample.',
                                        'parser': {'version': 'nested',
                                                   'source': 'rule:oracle',
                                                   'confidence': 1.0}}}),
            ],
            cost={'loyalty': -6},
        ),
        AbilitySpec(
            'activated',
            [
                EffectSpec('create_token', {'count': 2,
                            'power': 2,
                            'toughness': 2,
                            'colors': ['B', 'G'],
                            'subtypes': ['Wolf'],
                            'token_name': 'Wolf',
                            'oracle_text': 'When this creature dies, put a loyalty counter on '
                                           'each Garruk you control.'}),
            ],
            cost={'loyalty': 0},
        ),
    ]


register('Garruk, Cursed Huntsman', _garruk_cursed_huntsman)
