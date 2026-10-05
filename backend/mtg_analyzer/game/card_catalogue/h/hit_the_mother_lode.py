from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _hit_the_mother_lode() -> list[AbilitySpec]:
    """Discover 10. If the discovered card's mana value is less than 10, create a number of tapped Treasure
    tokens equal to the difference.

    — Reign of Dragons deck batch. `discover` (RULE 702.164) with the new ``treasures_below``: once the
    cast-or-take choice is made, the Treasures are the difference between 10 and the hit's mana value.
    """
    return [
        AbilitySpec("spell_effect", [EffectSpec("discover", {"mana_value": 10, "treasures_below": 10})]),
    ]


register("Hit the Mother Lode", _hit_the_mother_lode)
