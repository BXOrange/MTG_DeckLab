from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _nested_shambler() -> list[AbilitySpec]:
    """When this creature dies, create X tapped 1/1 green Squirrel creature tokens, where X is this creature's power.
    """
    return [
        AbilitySpec(
            'triggered',
            [
                EffectSpec('create_token', {'count': {'kind': 'characteristic',
                                      'characteristic': 'power',
                                      'of': 'self'},
                            'power': 1,
                            'toughness': 1,
                            'colors': ['G'],
                            'subtypes': ['Squirrel'],
                            'token_name': 'Squirrel',
                            'tapped': True}),
            ],
            trigger={'event': 'DIES', 'condition': {'subject': 'self'}},
        ),
    ]


register('Nested Shambler', _nested_shambler)
