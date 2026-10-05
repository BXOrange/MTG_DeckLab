from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _jacked_rabbit() -> list[AbilitySpec]:
    """Ravenous (This creature enters with X +1/+1 counters on it. If X is 5 or more, draw a card when it
    enters.)
    Whenever this creature attacks, create a number of 1/1 white Rabbit creature tokens equal to this
    creature's power.

    — Family Matters deck batch. Ravenous is the engine's RULE 702.156 keyword (entry counters off the
    announced X plus the draw trigger). The attack trigger is `create_token` counted by the source's own
    current power (the ``characteristic`` operand).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": {"kind": "characteristic", "characteristic": "power", "of": "self"},
                "power": 1, "toughness": 1, "colors": ["W"], "subtypes": ["Rabbit"], "token_name": "Rabbit",
            })],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
        ),
    ]


register("Jacked Rabbit", _jacked_rabbit)
