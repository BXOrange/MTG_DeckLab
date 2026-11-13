from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _shadow_the_hedgehog() -> list[AbilitySpec]:
    """Haste
    Whenever Shadow the Hedgehog or another creature you control with flash or haste dies, draw a card.
    Chaos Control — Each spell you cast has split second if mana from an artifact was spent to cast it. (As long as it's on the stack, players can't cast spells or activate abilities that aren't mana abilities.)
    """
    return [
        AbilitySpec('triggered', [EffectSpec('draw', {'count': 1})], trigger={
            'event': EventType.DIES,
            'condition': {'subject': 'self_or_group', 'controller': 'you', 'other': True,
                          'filter': {'card_type': 'creature', 'keyword_any': ['flash', 'haste']}},
        }),
        AbilitySpec('static', [EffectSpec('grant_spell_keyword', {
            'keywords': ['split_second'], 'artifact_mana_spent': True,
        })]),
    ]


register('Shadow the Hedgehog', _shadow_the_hedgehog)
