from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec
from .._shared.vehicle_animation import animate_vehicle
from ...card_registry.core import register


def _peacewalker_colossus() -> list[AbilitySpec]:
    """{1}{W}: Another target Vehicle you control becomes an artifact creature until end of turn.
    Crew 4 (Tap any number of creatures you control with total power 4 or more: This Vehicle becomes an artifact creature until end of turn.)

    — PLAY-ALL (Shorikai Vehicles). Crew is the keyword; the ability is the shared Vehicle animation on ``other_vehicle_you_control``.
    """
    return [AbilitySpec("activated", [animate_vehicle("other_vehicle_you_control")], cost={"mana": "{1}{W}"})]


register("Peacewalker Colossus", _peacewalker_colossus)
