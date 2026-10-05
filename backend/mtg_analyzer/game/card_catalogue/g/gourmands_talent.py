from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _gourmands_talent() -> list[AbilitySpec]:
    """(Gain the next level as a sorcery to add its ability.)
    During your turn, artifacts you control are Foods in addition to their other types and have "{2}, {T}, Sacrifice this artifact: You gain 3 life."
    {2}{G}: Level 2
    Whenever you gain life for the first time each turn, create a 3/3 green Raccoon creature token.
    {3}{G}: Level 3
    Whenever you gain life for the first time each turn, put a +1/+1 counter on each creature you control.
    """
    return [
        AbilitySpec(
            'activated',
            [
                EffectSpec('class_level', {'level': 2}),
            ],
            cost={'text': '{2}{g}', 'sorcery_speed_only': True, 'class_level': 2},
        ),
        AbilitySpec(
            'triggered',
            [
                EffectSpec('create_token', {'count': 1,
                            'power': 3,
                            'toughness': 3,
                            'colors': ['G'],
                            'subtypes': ['Raccoon'],
                            'keywords': [],
                            'token_name': 'Raccoon'}),
            ],
            trigger={'event': 'LIFE_GAINED',
                     'condition': {'subject': 'you'},
                     'limit': True,
                     'min_level': 2,
                     'level_counter': 'class_level'},
        ),
        AbilitySpec(
            'activated',
            [
                EffectSpec('class_level', {'level': 3}),
            ],
            cost={'text': '{3}{g}', 'sorcery_speed_only': True, 'class_level': 3},
        ),
        AbilitySpec(
            'triggered',
            [
                EffectSpec('add_counters', {'kind': '+1/+1',
                            'selector': 'each_creature_you_control',
                            'count': 1}),
            ],
            trigger={'event': 'LIFE_GAINED',
                     'condition': {'subject': 'you'},
                     'limit': True,
                     'min_level': 3,
                     'level_counter': 'class_level'},
        ),
        AbilitySpec(
            'static',
            [
                EffectSpec('type_change', {'affects': 'permanents_you_control',
                            'card_type': 'artifact',
                            'add_subtypes': ['Food'],
                            'active_player_only': True}),
            ],
        ),
        AbilitySpec(
            'static',
            [
                EffectSpec('grant_activated_ability', {'affects': 'permanents_you_control',
                            'card_type': 'artifact',
                            'active_player_only': True,
                            'cost': {'text': '{2}, {T}, Sacrifice this artifact'},
                            'grant_effects': [{'type': 'gain_life', 'params': {'amount': 3}}]}),
            ],
        ),
    ]


register("Gourmand's Talent", _gourmands_talent)
