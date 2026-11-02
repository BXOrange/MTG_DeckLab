from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _catacomb_dragon() -> list[AbilitySpec]:
    "Flying\nWhenever this creature becomes blocked by a nonartifact, non-Dragon creature, that creature gets -X/-0 until end of turn, where X is half the creature's power, rounded down."
    return [
        AbilitySpec(
            'triggered',
            [EffectSpec('bind', {"name": 'reduction', "amount": {'kind': 'characteristic', 'characteristic': 'power', 'of': 'trigger_subject', 'divide': 2}, "effects": [{'type': 'pump', 'params': {'power': '-$reduction', 'toughness': 0, 'trigger_subject': True}}]})],
            trigger={"event": EventType.BLOCKS, "related_to_source": True, "condition": {'subject': 'group', 'type': 'creature', 'filter': {'without_card_type': 'artifact', 'without_subtype': 'dragon'}}},
            raw_text='',
        ),
    ]


register('Catacomb Dragon', _catacomb_dragon)
