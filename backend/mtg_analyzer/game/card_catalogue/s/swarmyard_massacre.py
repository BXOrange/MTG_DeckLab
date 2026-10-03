from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _swarmyard_massacre() -> list[AbilitySpec]:
    """Create two 1/1 green Squirrel creature tokens. Then each creature that isn't an Insect, Rat, Spider, or Squirrel gets -1/-1 until end of turn for each creature you control that's an Insect, Rat, Spider, or Squirrel.
    """
    return [
        AbilitySpec(
            'spell_effect',
            [
                EffectSpec('create_token', {'count': 2,
                            'token_name': 'Squirrel',
                            'power': 1,
                            'toughness': 1,
                            'colors': ['G'],
                            'subtypes': ['Squirrel']}),
                EffectSpec('bind', {'amount': {'kind': 'count_selector',
                                       'selector': {'zone': 'battlefield',
                                                    'of': 'you',
                                                    'filter': {'card_type': 'creature',
                                                               'subtype_any': ['Insect',
                                                                               'Rat',
                                                                               'Spider',
                                                                               'Squirrel']}},
                                       'multiply': -1},
                            'effects': [{'type': 'pump',
                                         'params': {'power': '$n',
                                                    'toughness': '$n',
                                                    'selector': {'zone': 'battlefield',
                                                                 'of': 'any',
                                                                 'filter': {'card_type': 'creature',
                                                                            'without_subtype': ['Insect',
                                                                                                'Rat',
                                                                                                'Spider',
                                                                                                'Squirrel']}}}}]}),
            ],
        ),
    ]


register('Swarmyard Massacre', _swarmyard_massacre)
