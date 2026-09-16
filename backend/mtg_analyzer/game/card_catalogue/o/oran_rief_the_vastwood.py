from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# ``entered_this_turn`` object filter key (PAR-60)
# ===========================================================================
# `combat.matches_object_filter` gained an ``entered_this_turn`` key
# (`GameObject.turn_entered` vs the current turn), and `AddCountersEffect`'s
# ``selector`` branch now threads ``state`` into that call so a mass
# counter effect can narrow to just-entered creatures.


def _oran_rief_the_vastwood() -> list[AbilitySpec]:
    """This land enters tapped.  {T}: Add {G}.  (both from the land pipeline)
    {T}: Put a +1/+1 counter on each green creature that entered this turn."""
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("add_counters", {
                "kind": "+1/+1", "amount": 1, "selector": "each_creature",
                "creature_filter": {"color": "G", "entered_this_turn": True},
            })],
            cost={"text": "{T}"},
        ),
    ]


register("Oran-Rief, the Vastwood", _oran_rief_the_vastwood)
