from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _exploration_broodship() -> list[AbilitySpec]:
    """Station thresholds and a land sacrifice as a graveyard casting cost."""
    tier = {"min_level": 8, "level_counter": "charge"}
    return [
        AbilitySpec("static", [EffectSpec("extra_land_drop", {
            "affects": "you", "count": 1, "min_level": 3, "level_counter": "charge",
        })]),
        AbilitySpec("static", [EffectSpec("grant_keyword", {
            "keywords": ["flying"], "affects": "self", **tier,
        })]),
        AbilitySpec("static", [EffectSpec("type_change", {
            "add_types": ["creature"], "affects": "self", "power": 4, "toughness": 4, **tier,
        })]),
        AbilitySpec("static", [EffectSpec("graveyard_cast_permission", {
            "sacrifice_type": "land", "active_if": {"kind": "all", "conditions": [
                {"kind": "your_turn"},
                {"kind": "source_counters", "counter": "charge", "min": 8},
            ]},
        })]),
    ]


register("Exploration Broodship", _exploration_broodship)
