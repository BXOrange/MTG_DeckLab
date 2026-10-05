from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: "creatures with power 2 or less".
_MAX_BLOCKED_POWER = 2


def _sidar_kondo_of_jamuraa() -> list[AbilitySpec]:
    """Flanking (Whenever a creature without flanking blocks this creature, the blocking creature gets -1/-1 until end of turn.)
    Creatures your opponents control without flying or reach can't block creatures with power 2 or less.
    Partner (You can have two commanders if both have partner.)

    — PLAY-ALL (Abzan Armor). Flanking and Partner are keywords. The restriction is a `cant_block_filtered` combat restriction
    (RULE 509.1a: an attacker filter, ``max_power`` 2) carried by every opponent creature that lacks flying and reach
    (``object_filter`` with a keyword list, re-derived each recompute).
    """
    return [
        AbilitySpec("static", [EffectSpec("combat_restriction", {
            "kind": "cant_block_filtered", "filter": {"max_power": _MAX_BLOCKED_POWER},
            "affects": "creatures_opponents_control",
            "object_filter": {"without_keyword": ["flying", "reach"]},
        })]),
    ]


register("Sidar Kondo of Jamuraa", _sidar_kondo_of_jamuraa)
