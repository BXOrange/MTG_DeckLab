from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register
from ...costs import SACRIFICE_COUNT_X


def _insatiable_frugivore() -> list[AbilitySpec]:
    """When this creature enters, create a Food token, then you may exile three cards from your graveyard. If you do, repeat this process.
    {3}{B}, Sacrifice X Foods: Creatures you control get +X/+0 and gain menace until end of turn.
    """
    return [
        AbilitySpec(
            'triggered',
            [
                EffectSpec('repeat_food_exile_process', {}),
            ],
            trigger={'event': 'ENTERS_BATTLEFIELD', 'condition': {'subject': 'self'}},
        ),
        AbilitySpec(
            'activated',
            [
                EffectSpec('pump', {'power': 'x',
                            'toughness': 0,
                            'keywords': ['menace'],
                            'selector': 'creatures_you_control'}),
            ],
            cost={'mana': '{3}{B}', 'sacrifice_count': [SACRIFICE_COUNT_X, 'Food']},
        ),
    ]


register('Insatiable Frugivore', _insatiable_frugivore)
