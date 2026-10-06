from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _specs() -> list[AbilitySpec]:
    """
    Whenever a player casts a spell, if no colored mana was spent to cast it, counter that
    spell.
    """
    return [
        AbilitySpec(
            'triggered',
            [EffectSpec('counter', {'target_from_trigger_event': 'instance_id'})],
            trigger={'event': EventType.SPELL_CAST, 'any_player': True, 'spell_no_colored_mana_spent': True},
        ),
    ]


register('Void Mirror', _specs)
