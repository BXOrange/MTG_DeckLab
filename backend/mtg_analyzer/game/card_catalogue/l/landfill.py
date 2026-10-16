from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _landfill():
    """Choose a land type. Exile all lands you control of that type. Drop those cards, one at a time, onto the playing area from a height of at least one foot. Destroy each permanent completely covered by those cards. Then return the cards you dropped to the battlefield tapped."""
    return [AbilitySpec('spell_effect', [EffectSpec('landfill', {})])]


register('Landfill', _landfill)
