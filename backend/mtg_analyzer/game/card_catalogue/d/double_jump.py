from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _double_jump() -> list[AbilitySpec]:
    """Double Jump front half; Flying Kick and Fuse use the ordinary alternate-face binder."""
    return [AbilitySpec("spell_effect", [
        EffectSpec("add_counters", {"kind": "flying", "count": 1, "target_kind": "creature_you_control"}),
        EffectSpec("grant_until", {"target_kind": None, "previous_subject": True, "duration": "end_of_turn",
            "static": {"type": "pt_set", "params": {"power": 5, "toughness": 5}}}),
    ])]


register('Double Jump', _double_jump)
