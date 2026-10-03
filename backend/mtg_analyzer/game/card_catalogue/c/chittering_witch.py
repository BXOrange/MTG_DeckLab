from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _chittering_witch() -> list[AbilitySpec]:
    """When this creature enters, create a number of 1/1 black Rat creature tokens equal to the number of opponents you have.
    {1}{B}, Sacrifice a creature: Target creature gets -2/-2 until end of turn.
    """
    return [
        AbilitySpec(
            'activated',
            [
                EffectSpec('pump', {'power': -2, 'toughness': -2, 'target_kind': 'creature'}),
            ],
            cost={'text': '{1}{b}, sacrifice a creature'},
        ),
        AbilitySpec(
            'triggered',
            [
                EffectSpec('create_token', {'count': 1,
                            'per_opponent': True,
                            'power': 1,
                            'toughness': 1,
                            'colors': ['B'],
                            'subtypes': ['Rat'],
                            'token_name': 'Rat'}),
            ],
            trigger={'event': 'ENTERS_BATTLEFIELD', 'condition': {'subject': 'self'}},
        ),
    ]


register('Chittering Witch', _chittering_witch)
