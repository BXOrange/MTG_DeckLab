from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _bonecache_overseer() -> list[AbilitySpec]:
    "{T}, Pay 1 life: Draw a card. Activate only if three or more cards left your graveyard this turn or if you've sacrificed a Food this turn."
    return [
        AbilitySpec(
            'activated',
            [EffectSpec('draw', {"count": 1})],
            cost={"text": '{T}, Pay 1 life', "activation_condition": {'kind': 'any', 'conditions': [{'kind': 'event_this_turn', 'min': 3, 'trigger': {'event': 'CARD_LEFT_GRAVEYARD', 'graveyard_owner': 'you'}}, {'kind': 'event_this_turn', 'min': 1, 'trigger': {'event': 'SACRIFICE', 'condition': {'subject': 'group', 'controller': 'you', 'subtypes': ['food']}}}]}},
            raw_text='',
        ),
    ]


register('Bonecache Overseer', _bonecache_overseer)
