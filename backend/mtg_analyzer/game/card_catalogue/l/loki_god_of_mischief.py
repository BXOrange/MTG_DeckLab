from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _loki_god_of_mischief() -> list[AbilitySpec]:
    """Whenever a player or permanent becomes the target of an ability you control, draw a card. This ability triggers only once each turn."""
    return [AbilitySpec('triggered', [EffectSpec('draw', {'count': 1})], trigger={
        'event': EventType.TARGETS_ANNOUNCED,
        'condition': {'subject': 'global'},
        'caster_relation': 'you',
        'filter': {'item_kind': 'ability'},
        'limit': True,
    })]


register('Loki, God of Mischief', _loki_god_of_mischief)
