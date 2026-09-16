from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _killian_ink_duelist() -> list[AbilitySpec]:
    """Lifelink
    Menace
    Spells you cast that target a creature cost {2} less to cast."""
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cost_reduction", {
                "affects": "your_spells", "generic": 2,
                "reduce_if_targets": {"is_creature": True},
            })],
        ),
    ]


register("Killian, Ink Duelist", _killian_ink_duelist)
