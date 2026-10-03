from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _maskwood_nexus() -> list[AbilitySpec]:
    """Creatures you control are every creature type. The same is true for creature spells you control and creature cards you own that aren't on the battlefield.
    {3}, {T}: Create a 2/2 blue Shapeshifter creature token with changeling. (It is every creature type.)
    """
    return [
        AbilitySpec(
            'activated',
            [
                EffectSpec('create_token', {'count': 1,
                            'power': 2,
                            'toughness': 2,
                            'colors': ['U'],
                            'subtypes': ['Shapeshifter'],
                            'keywords': ['changeling'],
                            'token_name': 'Shapeshifter'}),
            ],
            cost={'text': '{3}, {t}'},
        ),
        AbilitySpec(
            'static',
            [
                EffectSpec('type_change', {'affects': 'creatures_you_control',
                            'add_subtypes': ['changeling'],
                            'off_battlefield': 'cards_you_own'}),
            ],
        ),
    ]


register('Maskwood Nexus', _maskwood_nexus)
