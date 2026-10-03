from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _the_odd_acorn_gang() -> list[AbilitySpec]:
    """Reach, menace, trample
    Squirrels you control have "{T}: Target Squirrel gets +2/+2 and gains trample until end of turn. Activate only as a sorcery."
    Whenever one or more Squirrels you control deal combat damage to a player, draw a card.
    """
    return [
        AbilitySpec(
            'keyword',
            [
            ],
            keyword={'name': 'reach'},
        ),
        AbilitySpec(
            'keyword',
            [
            ],
            keyword={'name': 'trample'},
        ),
        AbilitySpec(
            'keyword',
            [
            ],
            keyword={'name': 'menace'},
        ),
        AbilitySpec(
            'triggered',
            [
                EffectSpec('draw', {'count': 1}),
            ],
            trigger={'event': 'CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER',
                     'condition': {'subject': 'group',
                                   'controller': 'you',
                                   'other': False,
                                   'filter': {'subtype': 'squirrel'}},
                     'contributors': {'min': 1}},
        ),
        AbilitySpec(
            'static',
            [
                EffectSpec('grant_activated_ability', {'affects': 'creatures_you_control',
                            'subtype': 'Squirrel',
                            'cost': {'text': '{T}'},
                            'sorcery_speed_only': True,
                            'grant_effects': [{'type': 'pump',
                                               'params': {'power': 2,
                                                          'toughness': 2,
                                                          'keywords': ['trample'],
                                                          'target_kind': 'creature',
                                                          'creature_filter': {'subtype': 'Squirrel'}}}]}),
            ],
        ),
    ]


register('The Odd Acorn Gang', _the_odd_acorn_gang)
