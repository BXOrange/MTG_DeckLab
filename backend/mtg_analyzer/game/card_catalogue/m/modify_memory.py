from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _modify_memory() -> list[AbilitySpec]:
    """Exchange control of two target creatures controlled by different
    players. If you control neither creature, draw three cards.

    — The multi-target `count=2` + `distinct_controllers` mode (already
    shipped) plus the new `draw_if_neither_controlled` rider.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("exchange_control", {
                "target_kind": "creature", "count": 2, "distinct_controllers": True,
                "draw_if_neither_controlled": 3,
            })],
        ),
    ]


register("Modify Memory", _modify_memory)
