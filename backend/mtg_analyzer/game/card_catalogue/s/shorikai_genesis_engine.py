from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from .._shared.pilot import pilot_token
from ...card_registry.core import register


def _shorikai_genesis_engine() -> list[AbilitySpec]:
    """{1}, {T}: Draw two cards, then discard a card. Create a 1/1 colorless Pilot creature token with "This token crews Vehicles as though its power were 2 greater."
    Crew 8 (Tap any number of creatures you control with total power 8 or more: This Vehicle becomes an artifact creature until end of turn.)

    — PLAY-ALL (Shorikai Vehicles). Crew is the keyword; the draw/discard is the parser's, followed by the shared Pilot token.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("draw", {"count": 2}), EffectSpec("discard", {"count": 1}), pilot_token()],
            cost={"text": "{1}, {t}"},
        ),
    ]


register("Shorikai, Genesis Engine", _shorikai_genesis_engine)
