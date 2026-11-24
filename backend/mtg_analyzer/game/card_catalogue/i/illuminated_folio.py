
from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _illuminated_folio() -> list[AbilitySpec]:
    '{1}, {T}, Reveal two cards from your hand that share a color: Draw a card.'
    return [AbilitySpec('activated', [EffectSpec('draw', {'count': 1})],
                        cost={'mana': '{1}', 'taps_self': True, 'reveal_shared_color': 2})]


register('Illuminated Folio', _illuminated_folio)
