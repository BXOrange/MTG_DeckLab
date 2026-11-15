from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ....models.game.events import EventType
from ...card_registry.core import register


def _q_stacking_the_deck() -> list[AbilitySpec]:
    '''When Q enters, shuffle your library, then exile cards from the top of your library until you exile a nonland card. That nonland card gains "Exile a card from your hand: Create a copy of this card. You may cast the copy. Activate only during your turn and only if this card is exiled."'''
    return [AbilitySpec('triggered', [EffectSpec('shuffle_exile_grant_copy', {})],
                        trigger={'event': EventType.ENTERS_BATTLEFIELD, 'condition': {'subject': 'self'}})]


register('Q, Stacking the Deck', _q_stacking_the_deck)
