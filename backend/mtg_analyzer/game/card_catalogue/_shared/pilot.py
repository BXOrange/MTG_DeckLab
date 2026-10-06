"""The Pilot token shared by the Vehicle cards that make it (Prodigy's Prototype, Reckoner Bankbuster, Shorikai, Born to Drive)."""
from __future__ import annotations

from ....parser.oracle.spec import EffectSpec

#: The Pilot's rules text — `GameEngine._crew_power_of` reads the "crews Vehicles as though its power were N greater" bonus off it.
PILOT_TEXT = "This token crews Vehicles as though its power were 2 greater."


def pilot_token(count: int = 1) -> EffectSpec:
    """A fresh `create_token` spec for ``count`` 1/1 colorless Pilot creature tokens (never share one spec between cards)."""
    return EffectSpec("create_token", {
        "count": count, "power": 1, "toughness": 1, "colors": [], "subtypes": ["Pilot"], "token_name": "Pilot",
        "oracle_text": PILOT_TEXT,
    })
