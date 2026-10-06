from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from .._shared.pilot import pilot_token
from ...card_registry.core import register


def _reckoner_bankbuster() -> list[AbilitySpec]:
    """This Vehicle enters with three charge counters on it.
    {2}, {T}, Remove a charge counter from this Vehicle: Draw a card. Then if there are no charge counters on this Vehicle, create a Treasure token and a 1/1 colorless Pilot creature token with "This token crews Vehicles as though its power were 2 greater."
    Crew 3

    — PLAY-ALL (Shorikai Vehicles). Crew is the keyword and the three charge counters are the oracle-derived entry counters. The activation is the parser's
    draw with its counter-removal cost, then an `if_else` on ``source_counters`` (max 0) for the Treasure and the shared Pilot.
    """
    return [
        AbilitySpec(
            "activated",
            [
                EffectSpec("draw", {"count": 1}),
                EffectSpec("if_else", {
                    "condition": {"kind": "source_counters", "counter": "charge", "max": 0},
                    "then": [
                        {"type": "create_token", "params": {"token_name": "Treasure"}},
                        {"type": pilot_token().type, "params": pilot_token().params},
                    ],
                }),
            ],
            cost={"text": "{2}, {t}, remove a charge counter from ~"},
        ),
    ]


register("Reckoner Bankbuster", _reckoner_bankbuster)
