from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _specs() -> list[AbilitySpec]:
    """
    Whenever an artifact you control enters, put a loyalty counter on Tezzeret.
    0: Untap target artifact or creature. If it's an artifact creature, put a +1/+1 counter
    on it.
    −3: Search your library for an artifact card with mana value 1 or less, reveal it, put
    it into your hand, then shuffle.
    −7: You get an emblem with "At the beginning of combat on your turn, put three +1/+1
    counters on target artifact you control. If it's not a creature, it becomes a 0/0 Robot
    artifact creature."
    """
    return [
        AbilitySpec(
            'triggered',
            [EffectSpec('add_counters', {'target_kind': None, 'kind': 'loyalty', 'amount': 1})],
            trigger={
                'event': 'ENTERS_BATTLEFIELD',
                'condition': {'subject': 'group', 'type': 'artifact', 'you_control': True},
            },
        ),
        AbilitySpec(
            'activated',
            [
                EffectSpec('tap', {'target_kind': 'artifact_or_creature', 'untap': True}),
                EffectSpec(
                    'add_counters',
                    {'previous_subject': True, 'amount': 1, 'kind': '+1/+1'},
                    condition={
                        'kind': 'all',
                        'conditions': [
                            {'kind': 'is_card_type', 'of': 'previous_target', 'card_type': 'artifact'},
                            {'kind': 'is_card_type', 'of': 'previous_target', 'card_type': 'creature'},
                        ],
                    },
                ),
            ],
            cost={'loyalty': 0},
        ),
        AbilitySpec(
            'activated',
            [
                EffectSpec(
                    'search',
                    {'criteria': {'type': 'artifact', 'max_mana_value': 1}, 'destination': 'hand'},
                ),
            ],
            cost={'loyalty': -3},
        ),
        AbilitySpec(
            'activated',
            [
                EffectSpec(
                    'create_emblem',
                    {
                        'ability': {
                            'ability_kind': 'triggered',
                            'trigger': {
                                'event': 'STEP_BEGIN',
                                'filter': {'step': 'begin_combat'},
                                'phase_relation': 'you',
                            },
                            'effects': [
                                {
                                    'type': 'add_counters',
                                    'params': {
                                        'target_kind': 'artifact_you_control',
                                        'kind': '+1/+1',
                                        'amount': 3,
                                    },
                                },
                                {
                                    'type': 'grant_until',
                                    'params': {
                                        'static': {
                                            'type': 'type_change',
                                            'params': {
                                                'add_types': ['creature'],
                                                'add_subtypes': ['Robot'],
                                                'power': 0,
                                                'toughness': 0,
                                            },
                                        },
                                        'previous_subject': True,
                                        'duration': 'rest_of_game',
                                    },
                                    'condition': {
                                        'kind': 'not',
                                        'condition': {
                                            'kind': 'is_card_type',
                                            'of': 'previous_target',
                                            'card_type': 'creature',
                                        },
                                    },
                                },
                            ],
                        },
                    },
                ),
            ],
            cost={'loyalty': -7},
        ),
    ]


register('Tezzeret, Cruel Captain', _specs)
