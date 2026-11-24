
from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _benthic_explorers() -> list[AbilitySpec]:
    '{T}, Untap a tapped land an opponent controls: Add one mana of any type that land could produce.'
    return [AbilitySpec('static', [EffectSpec('grant_mana_ability', {
        'affects': 'self', 'mana': [{'C': 1}], 'color_selector': 'untapped_cost_land_types',
        'cost': {'taps_self': True, 'untap_others': [1, 'land'], 'untap_others_scope': 'opponents'},
    })])]


register('Benthic Explorers', _benthic_explorers)
