from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _specs() -> list[AbilitySpec]:
    """Lifelink
    Dance — At the beginning of your end step, each player may discard a card. Each player who discarded a card this way draws a card. If a creature card was discarded this way, you create a 1/2 white Moogle creature token with lifelink. Then if a noncreature card was discarded this way, put a +1/+1 counter on each Moogle you control.
    """
    return [
        AbilitySpec(
            'triggered',
            [
                EffectSpec('mark_event_log', {}),
                EffectSpec(
                    'for_each',
                    {
                        'over': {'players': 'each_player'},
                        'effects': [
                            {
                                'type': 'discard',
                                'params': {'target_kind': 'player', 'count_max': 1, 'then_draw_discarded': True},
                            },
                        ],
                    },
                ),
                EffectSpec(
                    'discarded_this_way_riders',
                    {
                        'creature_effects': [
                            {
                                'type': 'create_token',
                                'params': {
                                    'token_name': 'Moogle',
                                    'power': 1,
                                    'toughness': 2,
                                    'colors': ['W'],
                                    'subtypes': ['Moogle'],
                                    'keywords': ['lifelink'],
                                },
                            },
                        ],
                        'noncreature_effects': [
                            {
                                'type': 'add_counters',
                                'params': {
                                    'amount': 1,
                                    'kind': '+1/+1',
                                    'group': {
                                        'zone': 'battlefield',
                                        'of': 'you',
                                        'filter': {'subtype': 'moogle'},
                                    },
                                },
                            },
                        ],
                    },
                ),
            ],
            trigger={'event': EventType.STEP_BEGIN, 'filter': {'step': 'end'}, 'phase_relation': 'you'},
        ),
    ]


register('Mog, Moogle Warrior', _specs)
