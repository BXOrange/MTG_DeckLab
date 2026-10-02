from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _mana_reflection() -> list[AbilitySpec]:
    """If you tap a permanent for mana, it produces twice as much of that
    mana instead.

    — PLAY-ALL Step 2 (Hydranten). Nyxbloom Ancient's `mana_multiplier`
    static with a multiplier of 2 (`continuous.mana_production_multiplier_for`'s
    own docstring already names Mana Reflection as the shape it serves).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("mana_multiplier", {"multiplier": 2})],
        ),
    ]


register("Mana Reflection", _mana_reflection)
