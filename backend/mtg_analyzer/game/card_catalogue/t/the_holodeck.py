from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _the_holodeck() -> list[AbilitySpec]:
    """Once during each of your turns, you may play a permanent card you own from outside the game or from your graveyard."""
    return [AbilitySpec('static', [EffectSpec('graveyard_cast_permission', {
        'permanent_only': True, 'once_per_turn': True, 'plays_lands': True,
        'outside_game': True, 'active_if': {'kind': 'your_turn'},
    })])]


register('The Holodeck', _the_holodeck)
