from __future__ import annotations
from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

def _ashen_ghoul():
    """Haste
{B}: Return this card from your graveyard to the battlefield. Activate only during your upkeep and only if three or more creature cards are above this card."""
    return [AbilitySpec('activated', [EffectSpec('return_self_from_graveyard', {})],
        cost={'mana': '{B}', 'activation_condition': {'kind': 'all', 'conditions': [
            {'kind': 'your_upkeep'}, {'kind': 'graveyard_cards_above', 'min': 3, 'filter': {'card_type': 'creature'}},
        ]}})]
register('Ashen Ghoul', _ashen_ghoul)
