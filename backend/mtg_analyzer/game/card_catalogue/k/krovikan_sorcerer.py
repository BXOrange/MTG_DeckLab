from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _krovikan_sorcerer() -> list[AbilitySpec]:
    '{T}, Discard a nonblack card: Draw a card.\n{T}, Discard a black card: Draw two cards, then discard one of them.'
    return [AbilitySpec('activated', [EffectSpec('draw', {'count': 1})],
                        cost={'taps_self': True, 'discard': 1, 'discard_filter': 'nonblack'}),
            AbilitySpec('activated', [EffectSpec('draw_then_discard_drawn', {'count': 2, 'discard_count': 1})],
                        cost={'taps_self': True, 'discard': 1, 'discard_filter': 'black'})]


register('Krovikan Sorcerer', _krovikan_sorcerer)
