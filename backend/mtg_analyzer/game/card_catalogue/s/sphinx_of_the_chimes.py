
from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _sphinx_of_the_chimes() -> list[AbilitySpec]:
    'Flying\nDiscard two nonland cards with the same name: Draw four cards.'
    return [AbilitySpec('activated', [EffectSpec('draw', {'count': 4})],
                        cost={'discard': 2, 'discard_filter': 'nonland', 'discard_matching_names': True})]


register('Sphinx of the Chimes', _sphinx_of_the_chimes)
