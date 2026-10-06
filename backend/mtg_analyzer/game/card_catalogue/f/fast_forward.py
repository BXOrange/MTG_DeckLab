from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _fast_forward() -> list[AbilitySpec]:
    """Discount per distinct attacked opponent; goad the opposing creatures."""
    return [
        AbilitySpec("static", [EffectSpec("cost_reduction", {"affects": "self", "generic": 1,
            "per": "opponents_you_attacked_this_turn"})]),
        AbilitySpec("spell_effect", [EffectSpec("goad", {"selector": "creatures_opponents_control"})]),
    ]


register('Fast Forward', _fast_forward)
