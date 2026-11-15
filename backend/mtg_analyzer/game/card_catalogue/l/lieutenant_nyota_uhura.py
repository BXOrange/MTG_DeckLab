from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _lieutenant_nyota_uhura() -> list[AbilitySpec]:
    """Strange new worlds — {4}, {T}: Target opponent exiles the top X cards of their library, where X is the number of differently named lands you control. You may cast an instant or sorcery spell from among them without paying its mana cost. Then that player puts the rest on the bottom of their library in a random order."""
    return [AbilitySpec('activated', [EffectSpec('exile_opponent_top_cast_then_bottom', {
        'count': {'kind': 'count_selector', 'selector': {
            'zone': 'battlefield', 'of': 'you', 'filter': {'card_type': 'land'}, 'distinct': 'name',
        }},
    })], cost={'mana': '{4}', 'taps_self': True})]


register('Lieutenant Nyota Uhura', _lieutenant_nyota_uhura)
