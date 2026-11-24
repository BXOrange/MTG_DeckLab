from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _visitor_from_planet_q() -> list[AbilitySpec]:
    """All creature cards you own with flash are instants in addition to their other types.
    Whenever you cast another spell with two or more card types, you may draw a card, then discard a card.
    """
    return [
        AbilitySpec('static', [EffectSpec('grant_owned_card_type', {
            'add_types': ['instant'], 'filter': {'card_type': 'creature', 'keyword': 'flash'},
        })]),
        AbilitySpec('triggered', [EffectSpec('draw', {'count': 1}), EffectSpec('discard', {'count': 1})],
                    trigger={'event': EventType.SPELL_CAST, 'condition': {'subject': 'you'},
                             'spell_filter': {'min_card_types': 2, 'not_reference': True}}, optional=True),
    ]


register('Visitor from Planet Q', _visitor_from_planet_q)
