from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _sweet_gum_recluse() -> list[AbilitySpec]:
    """Flash
    Cascade
    Reach
    When this creature enters, put three +1/+1 counters on each of any number of target creatures that entered this turn.
    """
    return [AbilitySpec("triggered", [EffectSpec("add_counters", {
        "amount": 3, "kind": "+1/+1", "target_kind": "creature",
        "any_number": True, "optional": True, "creature_filter": {"entered_this_turn": True},
    })], trigger={"event": "ENTERS_BATTLEFIELD", "condition": {"subject": "self"}})]


register("Sweet-Gum Recluse", _sweet_gum_recluse)
