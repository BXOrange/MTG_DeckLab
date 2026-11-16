from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _jandor_s_ring() -> list[AbilitySpec]:
    '{2}, {T}, Discard the last card you drew this turn: Draw a card.'
    return [AbilitySpec('activated', [EffectSpec('draw', {'count': 1})],
                        cost={'mana': '{2}', 'taps_self': True, 'discard': 1,
                              'discard_filter': 'last_drawn_this_turn'})]


register("Jandor's Ring", _jandor_s_ring)
