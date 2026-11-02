from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _erayo_soratami_ascendant() -> list[AbilitySpec]:
    'Flying\nWhenever the fourth spell of a turn is cast, flip Erayo.'
    return [
        AbilitySpec(
            'triggered',
            [EffectSpec('flip', {})],
            trigger={"event": EventType.SPELL_CAST, "active_if": {'kind': 'event_this_turn', 'min': 4, 'max': 4, 'trigger': {'event': 'SPELL_CAST'}}},
            raw_text='',
        ),
    ]


register('Erayo, Soratami Ascendant', _erayo_soratami_ascendant)
