from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _special_move() -> list[AbilitySpec]:
    """Choose two modes, announcing all targets before resolution; Foot Toss sacrifices its damage dealer."""
    return [AbilitySpec("spell_effect", [], modes={"choose": 2, "options": [
        [EffectSpec("destroy", {"target_kind": "artifact"})],
        [EffectSpec("add_counters", {"count": 2, "target_kind": "creature_you_control",
            "creature_filter": {"attacking_or_blocking": True}})],
        [EffectSpec("damage_equal_to_power", {"dealer_kind": "creature_you_control", "target_kind": "any", "distinct": True}),
         EffectSpec("sacrifice_previous_dealer", {})],
    ], "descriptions": ["Jump Kick", "Dash Attack", "Foot Toss"]})]


register('Special Move', _special_move)
