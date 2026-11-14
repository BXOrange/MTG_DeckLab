from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _rootwater_shaman() -> list[AbilitySpec]:
    """You may cast Aura spells with enchant creature as though they had flash."""
    return [AbilitySpec('static', [EffectSpec('flash_permission', {'enchant_quality': 'creature'})])]


register('Rootwater Shaman', _rootwater_shaman)
