from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _bloatfly_swarm() -> list[AbilitySpec]:
    """Flying
    This creature enters with five +1/+1 counters on it.
    If damage would be dealt to this creature while it has a +1/+1 counter
    on it, prevent that damage, remove that many +1/+1 counters from it,
    then give each player a rad counter for each +1/+1 counter removed this
    way.

    — Bloatfly Swarm. Flying and the entry counters are picked up
    unconditionally (RULE 702 keyword fold-in / `entry_counters`, neither
    routed through the catalogue registry at all) — only the compound
    damage-prevention replacement needs hand-authoring here: "that many"
    ties both the counters removed *and* the rad counters granted to the
    damage amount that would have been dealt, known only inside the
    replacement itself at resolution time (`effects.
    _prevent_damage_convert_counters_replacement`), not a shape the oracle
    parser's plain `prevent_damage`/one-shot grammar can express.
    """
    return [
        AbilitySpec(
            "replacement",
            [EffectSpec("prevent_damage_convert_counters", {
                "to": "self", "remove_kind": "+1/+1", "grant_kind": "rad",
                "grant_selector": "each_player",
            })],
        ),
    ]


register("Bloatfly Swarm", _bloatfly_swarm)
