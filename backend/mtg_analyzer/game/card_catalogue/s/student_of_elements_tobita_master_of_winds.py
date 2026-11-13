from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _student_of_elements() -> list[AbilitySpec]:
    """When this creature has flying, flip it."""
    return [AbilitySpec('triggered', [EffectSpec('flip', {})], trigger={
        'event': EventType.STATE_CHECK,
        'state_condition': {'kind': 'has_keyword', 'keyword': 'flying'},
    })]


def _tobita() -> list[AbilitySpec]:
    """Creatures you control have flying."""
    return [AbilitySpec('static', [EffectSpec('grant_keyword', {
        'affects': 'creatures_you_control', 'keywords': ['flying'],
    })])]


register('Student of Elements', _student_of_elements)
register('Tobita, Master of Winds', _tobita)
