from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _fabrication_foundry() -> list[AbilitySpec]:
    '{T}: Add {W}. Spend this mana only to cast an artifact spell or activate an ability of an artifact source.\n{2}{W}, {T}, Exile one or more other artifacts you control with total mana value X: Return target artifact card with mana value X or less from your graveyard to the battlefield. Activate only as a sorcery.'
    return [AbilitySpec('activated', [EffectSpec('return_from_graveyard', {
        'target_kind': 'graveyard_artifact', 'max_mana_value': 'x',
    })], cost={'mana': '{2}{W}', 'taps_self': True, 'exile_others': (0, 'artifact'),
               'exile_others_total_mana_value_x': True, 'sorcery_speed_only': True})]


register('Fabrication Foundry', _fabrication_foundry)
