from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _card() -> list[AbilitySpec]:
    'Choose a number between 0 and 13. Each player sacrifices that many creatures of their choice.'
    return [
        AbilitySpec(
            'spell_effect',
            [EffectSpec('choose_number_then', {"min": 0, "max": 13, "then": [{'type': 'sacrifice', 'params': {'count': 'x', 'what': 'creature', 'selector': 'each_player'}}]})],
            raw_text='',
        ),
    ]


register('By Invitation Only', _card)
