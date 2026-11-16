
from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _thelon_of_havenwood() -> list[AbilitySpec]:
    'Each Fungus creature gets +1/+1 for each spore counter on it.\n{B}{G}, Exile a Fungus card from a graveyard: Put a spore counter on each Fungus on the battlefield.'
    return [AbilitySpec('static', [EffectSpec('anthem', {
        'affects': 'all_creatures', 'object_filter': {'subtype': 'Fungus'},
        'power': 1, 'toughness': 1,
        'power_count': {'counters_on': 'affected', 'kind': 'spore'},
        'toughness_count': {'counters_on': 'affected', 'kind': 'spore'},
    })]), AbilitySpec('activated', [EffectSpec('add_counters', {
        'amount': 1, 'kind': 'spore',
        'group': {'zone': 'battlefield', 'of': 'any', 'filter': {'subtype': 'Fungus'}},
    })], cost={'mana': '{B}{G}', 'exile_from_graveyard': 1,
               'exile_from_graveyard_filter': 'fungus', 'exile_from_graveyard_single': True})]



register('Thelon of Havenwood', _thelon_of_havenwood)
