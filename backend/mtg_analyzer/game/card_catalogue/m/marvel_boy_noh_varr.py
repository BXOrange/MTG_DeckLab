from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _marvel_boy_noh_varr() -> list[AbilitySpec]:
    """Whenever another creature you control enters and whenever you activate a power-up ability, put a +1/+1 counter on Marvel Boy."""
    return [
        AbilitySpec('triggered', [EffectSpec('add_counters', {'count': 1, 'kind': '+1/+1'})], trigger={
            'event': EventType.ENTERS_BATTLEFIELD,
            'condition': {'subject': 'group', 'controller': 'you', 'other': True, 'type': 'creature'},
        }),
        AbilitySpec('triggered', [EffectSpec('add_counters', {'count': 1, 'kind': '+1/+1'})], trigger={
            'event': EventType.ACTIVATED_ABILITY, 'condition': {'subject': 'you'},
            'filter': {'is_powerup_ability': True},
        }),
    ]


register('Marvel Boy, Noh-Varr', _marvel_boy_noh_varr)
