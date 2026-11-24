from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ....models.game.events import EventType
from ...card_registry.core import register


def _those_old_scientists() -> list[AbilitySpec]:
    '''(As this Saga enters and after your draw
    step, add a lore counter. Sacrifice after III.)
    I — Draw two cards, then discard two cards.
    II — Return up to one target artifact, instant, or sorcery card from your graveyard to your hand.
    III — Choose up to two target cards in graveyards. The owners of those cards shuffle them into their libraries.'''
    return [
        AbilitySpec('triggered', [EffectSpec('draw', {'count': 2}), EffectSpec('discard', {'count': 2})],
                    trigger={'event': EventType.SAGA_CHAPTER, 'chapter': [1]}),
        AbilitySpec('triggered', [EffectSpec('return_from_graveyard', {
            'target_kind': 'graveyard_instant_sorcery_or_artifact', 'optional': True, 'destination': 'hand'})],
                    trigger={'event': EventType.SAGA_CHAPTER, 'chapter': [2]}),
        AbilitySpec('triggered', [EffectSpec('return_from_graveyard', {
            'target_kind': 'any_graveyard_card', 'count': 2, 'optional': True,
            'destination': 'library_bottom', 'shuffle_after': True})],
                    trigger={'event': EventType.SAGA_CHAPTER, 'chapter': [3]}),
    ]


register('Those Old Scientists', _those_old_scientists)
