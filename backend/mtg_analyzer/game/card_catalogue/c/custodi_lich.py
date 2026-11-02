from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _custodi_lich() -> list[AbilitySpec]:
    'When this creature enters, you become the monarch.\nWhenever you become the monarch, target player sacrifices a creature of their choice.'
    return [
        AbilitySpec(
            'triggered',
            [EffectSpec('become_monarch', {})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {'subject': 'self'}},
            raw_text='when ~ enters, you become the monarch.',
        ),
        AbilitySpec(
            'triggered',
            [EffectSpec('sacrifice', {"what": 'creature', "target_kind": 'player'})],
            trigger={"event": EventType.BECAME_MONARCH, "condition": {'subject': 'you'}},
            raw_text='',
        ),
    ]


register('Custodi Lich', _custodi_lich)
