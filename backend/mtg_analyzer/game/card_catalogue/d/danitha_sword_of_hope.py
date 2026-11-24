from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _danitha_sword_of_hope() -> list[AbilitySpec]:
    """First strike
    Whenever you cast an Equipment spell or a spell that targets a creature you control, draw a card. This ability triggers only once each turn.
    """
    return [AbilitySpec('triggered', [EffectSpec('draw', {'count': 1})], trigger={
        'event': EventType.SPELL_CAST,
        'condition': {'subject': 'you'},
        'spell_targets': {'card_type': 'creature', 'you_control': True},
        'spell_targets_or_equipment': True,
        'limit': True,
    })]


register('Danitha, Sword of Hope', _danitha_sword_of_hope)
