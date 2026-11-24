from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _vulcan_mind_meld() -> list[AbilitySpec]:
    """Target opponent looks at the top card of your library, then exiles it face down. You look at the top two cards of their library, then exile them face down. For each card exiled this way, the player who exiled it may play it for as long as it remains exiled. Mana of any type can be spent to cast spells this way."""
    return [AbilitySpec('spell_effect', [EffectSpec('exchange_top_library_permissions', {
        'own_count': 1, 'opponent_count': 2,
    })])]


register('Vulcan Mind-Meld', _vulcan_mind_meld)
