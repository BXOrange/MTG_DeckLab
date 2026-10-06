from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register
from .double_jump import _double_jump


def _double_jump_flying_kick() -> list[AbilitySpec]:
    """RULE 709.4: a fused cast resolves Double Jump, then Flying Kick."""
    return _double_jump() + [AbilitySpec("spell_effect", [EffectSpec("damage_equal_to_power", {
        "dealer_kind": "creature_you_control", "target_kind": "creature_you_dont_control",
    })])]


register("Double Jump // Flying Kick", _double_jump_flying_kick)
