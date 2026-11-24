from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _nyx_herald() -> list[AbilitySpec]:
    """At the beginning of combat on your turn, target enchanted creature or enchantment creature you control gets +1/+1 and gains trample until end of turn."""
    return [AbilitySpec('triggered', [EffectSpec('pump', {
        'power': 1, 'toughness': 1, 'keywords': ['trample'],
        'target_kind': 'creature_you_control',
        'creature_filter': {'any_of': [{'enchanted': True}, {'card_type': 'enchantment'}]},
    })], trigger={
        'event': EventType.STEP_BEGIN, 'filter': {'step': 'begin_combat'}, 'phase_relation': 'you',
    })]


register('Nyx Herald', _nyx_herald)
