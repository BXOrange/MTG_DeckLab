from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.catalogue.player_event_head import THIS_DOOR
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: "two +1/+1 counters and a trample counter".
_PLUS_COUNTERS = 2


def _experimental_lab() -> list[AbilitySpec]:
    """When you unlock this door, manifest dread, then put two +1/+1 counters and a trample counter on that creature.
    (You may cast either half. That door unlocks on the battlefield. As a sorcery, you may pay the mana cost of a locked door to unlock it.)

    — PLAY-ALL (Jump Scare!). The left door's text (`game/rooms.py` binds it only while that door is unlocked, MEC-111).
    `manifest_dread` leaves
    the manifested creature as the next clauses' referent (`created_objects`, also across the look-at-two pause), which
    `add_counters` ``previous_subject`` reads for the counters.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("manifest_dread", {}),
                EffectSpec("add_counters", {"count": _PLUS_COUNTERS, "kind": "+1/+1", "previous_subject": True}),
                EffectSpec("add_counters", {"count": 1, "kind": "trample", "previous_subject": True}),
            ],
            trigger={"event": EventType.DOOR_UNLOCKED, "condition": {"subject": "self"}, "filter": {"door": THIS_DOOR}},
        ),
    ]


register("Experimental Lab", _experimental_lab)
