from __future__ import annotations
from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

def _cinder_crawler():
    """{R}: This creature gets +1/+0 until end of turn. Activate only if this creature is blocked."""
    return [AbilitySpec('activated', [EffectSpec('pump', {'power': 1, 'toughness': 0})],
        cost={'mana': '{R}', 'activation_condition': {'kind': 'source_blocked'}})]
register('Cinder Crawler', _cinder_crawler)
