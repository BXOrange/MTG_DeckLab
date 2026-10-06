from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _specs() -> list[AbilitySpec]:
    """
    (Gain the next level as a sorcery to add its ability.)
    Spells your opponents cast during your turn cost {1} more to cast.
    {2}{W}: Level 2
    Creatures you control get +1/+1.
    {4}{W}: Level 3
    Whenever you attack, until end of turn, target attacking creature gets +1/+1 for each
    other attacking creature and gains double strike.
    """
    return [
        AbilitySpec(
            'static',
            [
                EffectSpec(
                    'cost_reduction',
                    {
                        'affects': 'opponents_spells',
                        'generic': 1,
                        'increase': True,
                        'active_if': {'kind': 'your_turn'},
                    },
                ),
            ],
        ),
        AbilitySpec(
            'activated',
            [EffectSpec('class_level', {'level': 2})],
            cost={'text': '{2}{W}', 'sorcery_speed_only': True, 'class_level': 2},
        ),
        AbilitySpec(
            'static',
            [
                EffectSpec(
                    'anthem',
                    {
                        'affects': 'creatures_you_control',
                        'power': 1,
                        'toughness': 1,
                        'min_level': 2,
                        'level_counter': 'class_level',
                    },
                ),
            ],
        ),
        AbilitySpec(
            'activated',
            [EffectSpec('class_level', {'level': 3})],
            cost={'text': '{4}{W}', 'sorcery_speed_only': True, 'class_level': 3},
        ),
        AbilitySpec(
            'triggered',
            [EffectSpec('pump_attacker_per_other_attacker', {'keywords': ['double_strike']})],
            trigger={
                'event': EventType.PLAYER_ATTACKED,
                'condition': {'subject': 'you'},
                'min_level': 3,
                'level_counter': 'class_level',
            },
        ),
    ]


register('Paladin Class', _specs)
