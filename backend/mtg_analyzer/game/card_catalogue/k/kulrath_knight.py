from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _kulrath_knight() -> list[AbilitySpec]:
    """Flying
    Wither (This deals damage to creatures in the form of -1/-1 counters.)
    Creatures your opponents control with counters on them can't attack
    or block.

    Flying + Wither fold in from the RULE 702 keyword catalogue. Authored:
    the static (RULE 613.7f layer-6 grant) that hands ``cant_attack`` /
    ``cant_block`` — the synthetic flag keywords `game/combat.py` already
    reads at declare-attackers / declare-blockers — to the new
    ``creatures_opponents_control_with_a_counter`` affected set (any
    counter kind, RULE 122.1).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {
                "affects": "creatures_opponents_control_with_a_counter",
                "keywords": ["cant_attack", "cant_block"],
            })],
        ),
    ]


register("Kulrath Knight", _kulrath_knight)
