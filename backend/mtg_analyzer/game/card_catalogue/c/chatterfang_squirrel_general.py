from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register
from ...costs import SACRIFICE_COUNT_X


def _chatterfang_squirrel_general() -> list[AbilitySpec]:
    """Forestwalk (This creature can't be blocked as long as defending player controls a Forest.)
    If one or more tokens would be created under your control, those tokens plus that many 1/1 green Squirrel creature tokens are created instead.
    {B}, Sacrifice X Squirrels: Target creature gets +X/-X until end of turn.
    """
    return [
        AbilitySpec(
            'keyword',
            [
            ],
            keyword={'name': 'landwalk', 'quality': 'forest'},
        ),
        AbilitySpec(
            'replacement',
            [
                EffectSpec('additional_creature_tokens', {'token_name': 'Squirrel',
                            'power': 1,
                            'toughness': 1,
                            'colors': ['G'],
                            'subtypes': ['Squirrel']}),
            ],
        ),
        AbilitySpec(
            'activated',
            [
                EffectSpec('pump', {'power': 'x', 'toughness': '-x', 'target_kind': 'creature'}),
            ],
            cost={'mana': '{B}', 'sacrifice_count': [SACRIFICE_COUNT_X, 'Squirrel']},
        ),
    ]


register('Chatterfang, Squirrel General', _chatterfang_squirrel_general)
