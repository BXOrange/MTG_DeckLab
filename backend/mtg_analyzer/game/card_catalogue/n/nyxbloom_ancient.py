from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _nyxbloom_ancient() -> list[AbilitySpec]:
    """Trample
    If you tap a permanent for mana, it produces three times as much of
    that mana instead.

    — MEC-12 (cEDH Kinnan). The new `mana_multiplier` static
    (`continuous.mana_production_multiplier_for`, consulted directly by
    `GameEngine.tap_for_mana`) — Trample is a printed keyword, recognized
    independently of this entry.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("mana_multiplier", {"multiplier": 3})],
        ),
    ]


register("Nyxbloom Ancient", _nyxbloom_ancient)
