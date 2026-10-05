from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _gaddock_teeg() -> list[AbilitySpec]:
    """Noncreature spells with mana value 4 or greater can't be cast.
    Noncreature spells with {X} in their mana costs can't be cast.

    — MEC-43, one of `cast_prohibition`'s two "shared primitive" clusters:
    the first clause needed a **literal** threshold (`max_mana_value`, new
    — every prior `cast_prohibition` card read a dynamic `count_selector`
    instead), the second a wholly independent flat check on the printed
    cost string (`has_x_cost`) unrelated to mana value at all. Two
    separate statics rather than one combined check, since a spell can
    trip either clause without the other (a noncreature {X} spell of mana
    value 2 is still illegal). ``scope="all"``: unlike the "opponents"
    default this static family started with, Gaddock Teeg restricts
    *every* player, its own controller included.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cast_prohibition", {
                "scope": "all", "noncreature": True, "max_mana_value": 3,
            })],
        ),
        AbilitySpec(
            "static",
            [EffectSpec("cast_prohibition", {
                "scope": "all", "noncreature": True, "has_x_cost": True,
            })],
        ),
    ]


register("Gaddock Teeg", _gaddock_teeg)
