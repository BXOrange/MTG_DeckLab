from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec
from .._shared.vehicle_animation import animate_vehicle
from ...card_registry.core import register


def _mobilizer_mech() -> list[AbilitySpec]:
    """Flying
    Whenever this Vehicle becomes crewed, up to one other target Vehicle you control becomes an artifact creature until end of turn.
    Crew 3 (Tap any number of creatures you control with total power 3 or more: This Vehicle becomes an artifact creature until end of turn.)

    — PLAY-ALL (Shorikai Vehicles). Flying and Crew are keywords. The head is the new `CREWED` event (RULE 702.122e, fired by the last effect of every
    Crew ability); the body is the shared Vehicle animation on an optional ``other_vehicle_you_control``.
    """
    return [
        AbilitySpec(
            "triggered", [animate_vehicle("other_vehicle_you_control", optional=True)],
            trigger={"event": EventType.CREWED, "condition": {"subject": "self"}},
        ),
    ]


register("Mobilizer Mech", _mobilizer_mech)
