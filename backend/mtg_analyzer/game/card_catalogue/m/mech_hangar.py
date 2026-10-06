from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec
from .._shared.vehicle_animation import animate_vehicle
from ...card_registry.core import register


def _mech_hangar() -> list[AbilitySpec]:
    """{T}: Add {C}.
    {T}: Add one mana of any color. Spend this mana only to cast a Pilot or Vehicle spell.
    {3}, {T}: Target Vehicle becomes an artifact creature until end of turn.

    — PLAY-ALL (Shorikai Vehicles). The two mana abilities are auto-bound from the text; the third is the shared Vehicle animation
    (`_shared/vehicle_animation.py`: a `type_change` with ``pt_selector: vehicle``) on any target Vehicle.
    """
    return [AbilitySpec("activated", [animate_vehicle("vehicle")], cost={"mana": "{3}", "taps_self": True})]


register("Mech Hangar", _mech_hangar)
