from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _mistveil_plains() -> list[AbilitySpec]:
    """({T}: Add {W}.)
    This land enters tapped.
    {W}, {T}: Put target card from your graveyard on the bottom of your
    library. Activate only if you control two or more white permanents.

    Documented simplification: the "activate only if you control two or more
    white permanents" gate is not modeled — the ability is always
    available."""
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("graveyard_to_library_bottom_random", {"target_kind": "graveyard_card"})],
            cost={"mana": "{W}", "taps_self": True},
        ),
    ]


register("Mistveil Plains", _mistveil_plains)
