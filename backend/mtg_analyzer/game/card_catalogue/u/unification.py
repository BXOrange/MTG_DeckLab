from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ....models.game.events import EventType
from ...card_registry.core import register


def _unification() -> list[AbilitySpec]:
    '''(As this Saga enters and after your draw step, add a lore counter. Sacrifice after III.)
    I — The owner of up to one target creature draws two cards, then shuffles that creature into their library.
    II — You may put a Spacecraft card from your hand or graveyard onto the battlefield.
    III — You and target opponent each draw two cards.'''
    return [
        AbilitySpec('triggered', [EffectSpec('owner_draw_then_shuffle', {})],
                    trigger={'event': EventType.SAGA_CHAPTER, 'chapter': [1]}),
        AbilitySpec('triggered', [EffectSpec('put_from_hand_onto_battlefield', {
            'criteria': {'type': 'spacecraft'}, 'count': 1, 'zones': ['hand', 'graveyard']})],
                    trigger={'event': EventType.SAGA_CHAPTER, 'chapter': [2]}, optional=True),
        AbilitySpec('triggered', [EffectSpec('draw', {'count': 2}),
                                EffectSpec('draw', {'count': 2, 'target_kind': 'opponent'})],
                    trigger={'event': EventType.SAGA_CHAPTER, 'chapter': [3]}),
    ]


register('Unification', _unification)
