from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec
from .._shared.pilot import pilot_token
from ...card_registry.core import register


def _prodigy_s_prototype() -> list[AbilitySpec]:
    """Whenever one or more Vehicles you control attack, create a 1/1 colorless Pilot creature token with "This token crews Vehicles as though its power were 2 greater."
    Crew 2 (Tap any number of creatures you control with total power 2 or more: This Vehicle becomes an artifact creature until end of turn.)

    — PLAY-ALL (Shorikai Vehicles). Crew is the keyword. The head is Neriv's `ATTACKERS_DECLARED` count (at least one declared attacker with the Vehicle
    subtype); the token is the shared Pilot (`_shared/pilot.py`).
    """
    return [
        AbilitySpec(
            "triggered", [pilot_token()],
            trigger={
                "event": EventType.ATTACKERS_DECLARED, "condition": {"subject": "you"},
                "attackers_declared": {"filter": {"subtype": "vehicle"}, "min": 1},
            },
        ),
    ]


register("Prodigy's Prototype", _prodigy_s_prototype)
