from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _radagast_of_rhosgobel() -> list[AbilitySpec]:
    """The first creature spell you cast each turn costs {2} less to cast and can be cast as though it had flash."""
    return [
        AbilitySpec('static', [EffectSpec('cost_reduction', {
            'generic': 2, 'spell_type': 'creature',
            'active_if': {'kind': 'first_creature_spell_this_turn'},
        })]),
        AbilitySpec('static', [EffectSpec('flash_permission', {
            'creature_only': True, 'active_if': {'kind': 'first_creature_spell_this_turn'},
        })]),
    ]


register('Radagast of Rhosgobel', _radagast_of_rhosgobel)
