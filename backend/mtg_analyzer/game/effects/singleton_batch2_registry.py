"""Registers the effect factories added for the Batch 2 hand-authored singletons (one `EFFECT_FACTORIES` per module)."""
from __future__ import annotations

from .copy_distinctly_named_tokens import EFFECT_FACTORIES as _COPY_DISTINCTLY_NAMED_TOKENS
from .core import EffectRegistry
from .damage_source_sacrifice_or_lose import EFFECT_FACTORIES as _DAMAGE_SOURCE_SACRIFICE_OR_LOSE
from .exile_spell_and_plot import EFFECT_FACTORIES as _EXILE_SPELL_AND_PLOT

for _factories in (_COPY_DISTINCTLY_NAMED_TOKENS, _DAMAGE_SOURCE_SACRIFICE_OR_LOSE, _EXILE_SPELL_AND_PLOT):
    for _name, _factory in _factories.items():
        EffectRegistry.register(_name, _factory)
