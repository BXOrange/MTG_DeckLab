from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _azure_fleet_admiral() -> list[AbilitySpec]:
    """When this creature enters, you become the monarch.
    This creature can't be blocked by creatures the monarch controls.

    The qualified ``cant_be_blocked_by`` restriction (RULE 509.1b) over a ``controlled_by_monarch`` blocker filter
    (RULE 726.1: the monarch designation belongs to a player; `matches_object_filter` reads ``state.monarch_id``).
    """
    return [
        AbilitySpec("triggered", [EffectSpec("become_monarch", {})],
                    trigger={"event": "ENTERS_BATTLEFIELD", "condition": {"subject": "self"}}),
        AbilitySpec("static", [EffectSpec("combat_restriction", {
            "affects": "self", "kind": "cant_be_blocked_by", "filter": {"controlled_by_monarch": True},
        })]),
    ]


register("Azure Fleet Admiral", _azure_fleet_admiral)
