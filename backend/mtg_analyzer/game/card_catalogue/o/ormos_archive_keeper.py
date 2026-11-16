from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _ormos_archive_keeper() -> list[AbilitySpec]:
    'Flying\nIf you would draw a card while your library has no cards in it, instead put five +1/+1 counters on Ormos.\n{1}{U}{U}, Discard three cards with different names: Draw five cards.'
    return [AbilitySpec('replacement', [EffectSpec('counters_instead_of_empty_draw', {'amount': 5})]),
            AbilitySpec('activated', [EffectSpec('draw', {'count': 5})],
                        cost={'mana': '{1}{U}{U}', 'discard': 3, 'discard_different_names': True})]


register('Ormos, Archive Keeper', _ormos_archive_keeper)
