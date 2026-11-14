from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _tegwyll_s_scouring() -> list[AbilitySpec]:
    """You may cast this spell as though it had flash by tapping three untapped creatures you control with flying in addition to paying its other costs.
    Destroy all creatures. Create three 1/1 black Faerie Rogue creature tokens with flying.
    """
    return [AbilitySpec('spell_effect', [
        EffectSpec('destroy', {'selector': 'all_creatures'}),
        EffectSpec('create_token', {'count': 3, 'power': 1, 'toughness': 1,
            'colors': ['B'], 'subtypes': ['Faerie', 'Rogue'], 'keywords': ['flying'],
            'token_name': 'Faerie Rogue'}),
    ], additional_cost={'tap_others': [3, 'creature_flying']}, additional_cost_optional=True,
       conditional_flash={'active_if': {'kind': 'flag', 'flag': 'additional_cost_paid'}})]


register("Tegwyll's Scouring", _tegwyll_s_scouring)
