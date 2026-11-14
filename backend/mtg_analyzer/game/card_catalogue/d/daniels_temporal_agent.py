from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ....models.game.events import EventType
from ...card_registry.core import register


def _daniels_temporal_agent() -> list[AbilitySpec]:
    '''When Daniels enters, return target creature card from your graveyard to your hand.
    {2}, Put this card from your graveyard on the bottom of your library: You gain 2 life.'''
    return [
        AbilitySpec('triggered', [EffectSpec('return_from_graveyard', {
            'target_kind': 'graveyard_creature', 'destination': 'hand'})],
            trigger={'event': EventType.ENTERS_BATTLEFIELD, 'condition': {'subject': 'self'}}),
        AbilitySpec('activated', [EffectSpec('gain_life', {'amount': 2})], cost={
            'mana': '{2}', 'activation_zones': ['graveyard'], 'bottom_self_from_graveyard': True}),
    ]


register('Daniels, Temporal Agent', _daniels_temporal_agent)
