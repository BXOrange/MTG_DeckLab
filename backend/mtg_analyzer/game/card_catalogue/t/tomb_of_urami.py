
from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _tomb_of_urami() -> list[AbilitySpec]:
    "{T}: Add {B}. Tomb of Urami deals 1 damage to you if you don't control an Ogre.\n{2}{B}{B}, {T}, Sacrifice all lands you control: Create Urami, a legendary 5/5 black Demon Spirit creature token with flying."
    return [AbilitySpec('activated', [EffectSpec('create_token', {
        'count': 1, 'token_name': 'Urami', 'power': 5, 'toughness': 5,
        'colors': ['B'], 'subtypes': ['Demon', 'Spirit'], 'keywords': ['flying'], 'legendary': True,
    })], cost={'mana': '{2}{B}{B}', 'taps_self': True, 'sacrifice_all_lands': True})]



register('Tomb of Urami', _tomb_of_urami)
