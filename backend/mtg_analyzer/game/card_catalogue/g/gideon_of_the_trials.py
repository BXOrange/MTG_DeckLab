from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _specs() -> list[AbilitySpec]:
    """
    +1: Until your next turn, prevent all damage target permanent would deal.
    0: Until end of turn, Gideon becomes a 4/4 Human Soldier creature with indestructible
    that's still a planeswalker. Prevent all damage that would be dealt to him this turn.
    0: You get an emblem with "As long as you control a Gideon planeswalker, you can't lose
    the game and your opponents can't win the game."
    """
    gate = {
        'kind': 'control_count',
        'selector': {
            'zone': 'battlefield',
            'of': 'you',
            'filter': {'card_type': 'planeswalker', 'subtype': 'Gideon'},
        },
        'min': 1,
    }
    return [
        AbilitySpec(
            'activated',
            [EffectSpec('prevent_source_damage_until_next_turn', {})],
            cost={'loyalty': 1},
        ),
        AbilitySpec(
            'activated',
            [
                EffectSpec(
                    'grant_until',
                    {
                        'static': {
                            'type': 'type_change',
                            'params': {
                                'add_types': ['creature'],
                                'add_subtypes': ['Human', 'Soldier'],
                                'power': 4,
                                'toughness': 4,
                            },
                        },
                        'extra_statics': [{'type': 'grant_keyword', 'params': {'keywords': ['indestructible']}}],
                        'duration': 'end_of_turn',
                        'self_subject': True,
                    },
                ),
                EffectSpec('prevent_damage_shield', {'self_only': True, 'amount': 'all'}),
            ],
            cost={'loyalty': 0},
        ),
        AbilitySpec(
            'activated',
            [
                EffectSpec(
                    'create_emblem',
                    {
                        'abilities': [
                            {
                                'ability_kind': 'static',
                                'effects': [
                                    {'type': 'cant_lose_game', 'params': {'active_if': gate}},
                                    {'type': 'opponents_cant_win', 'params': {'active_if': gate}},
                                ],
                            },
                        ],
                    },
                ),
            ],
            cost={'loyalty': 0},
        ),
    ]


register('Gideon of the Trials', _specs)
