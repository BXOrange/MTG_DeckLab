from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _king_of_the_oathbreakers() -> list[AbilitySpec]:
    """Flying
    Whenever King of the Oathbreakers or another Spirit you control becomes the target of a spell, it phases out. (Treat it and anything attached to it as though they don't exist until your next turn.)
    Whenever King of the Oathbreakers or another Spirit you control phases in, create a tapped 1/1 white Spirit creature token with flying.
    """
    return [
        AbilitySpec('triggered', [EffectSpec('phase_out', {'trigger_subject': True})], trigger={
            'event': EventType.BECOMES_TARGET,
            'condition': {'subject': 'self_or_group', 'controller': 'you', 'other': True,
                          'filter': {'subtype': 'spirit'}},
            'filter': {'item_kind': 'spell'},
        }),
        AbilitySpec('triggered', [EffectSpec('create_token', {
            'count': 1, 'power': 1, 'toughness': 1, 'colors': ['W'], 'subtypes': ['Spirit'],
            'keywords': ['flying'], 'token_name': 'Spirit', 'tapped': True,
        })], trigger={
            'event': EventType.PHASED_IN,
            'condition': {'subject': 'self_or_group', 'controller': 'you', 'other': True,
                          'filter': {'subtype': 'spirit'}},
        }),
    ]


register('King of the Oathbreakers', _king_of_the_oathbreakers)
