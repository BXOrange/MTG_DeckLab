"""Registers the effect factories added for the Batch 2 hand-authored singletons, worker H (one `EFFECT_FACTORIES` per
module)."""
from __future__ import annotations

from .captured_counters import EFFECT_FACTORIES as _CAPTURED_COUNTERS
from .core import EffectRegistry
from .damage_source_pays_or_loses_life import EFFECT_FACTORIES as _DAMAGE_SOURCE_PAYS_OR_LOSES_LIFE

for _factories in (_CAPTURED_COUNTERS, _DAMAGE_SOURCE_PAYS_OR_LOSES_LIFE):
    for _name, _factory in _factories.items():
        EffectRegistry.register(_name, _factory)
