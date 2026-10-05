from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _muldrotha_the_gravetide() -> list[AbilitySpec]:
    return [AbilitySpec(
        "static", [EffectSpec("graveyard_cast_permission", {
            "per_permanent_type": True, "once_per_turn": False,
        })],
    )]


register("Muldrotha, the Gravetide", _muldrotha_the_gravetide)
