from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _chandra_s_ignition() -> list[AbilitySpec]:
    """Target creature you control deals damage equal to its power to each other creature and each
    opponent.

    — Reign of Dragons deck batch. `damage_equal_to_power` with a creature-you-control dealer target
    and the new ``each_other_creature_and_opponent`` selector, scoped to the dealer (every other
    creature on the battlefield, whoever controls it, plus each opponent of the dealer's controller).
    """
    return [
        AbilitySpec("spell_effect", [EffectSpec("damage_equal_to_power", {
            "dealer_kind": "creature_you_control", "selector": "each_other_creature_and_opponent",
        })]),
    ]


register("Chandra's Ignition", _chandra_s_ignition)
