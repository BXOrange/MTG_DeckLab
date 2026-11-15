from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ....models.game.events import EventType
from ...card_registry.core import register


def _ensign_pavel_chekov() -> list[AbilitySpec]:
    """Strange new worlds — When Ensign Chekov enters, each opponent exiles the top X cards of their library, where X is the number of differently named lands you control. For each opponent, choose a land card that player owns exiled this way. You may play the chosen cards for as long as they remain exiled."""
    return [AbilitySpec('triggered', [EffectSpec('exile_opponents_choose_lands', {
        'count': {'kind': 'count_selector', 'selector': {
            'zone': 'battlefield', 'of': 'you', 'filter': {'card_type': 'land'}, 'distinct': 'name',
        }},
    })], trigger={'event': EventType.ENTERS_BATTLEFIELD, 'condition': {'subject': 'self'}})]


register('Ensign Pavel Chekov', _ensign_pavel_chekov)
