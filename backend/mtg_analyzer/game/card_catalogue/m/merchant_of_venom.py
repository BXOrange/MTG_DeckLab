from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _merchant_of_venom() -> list[AbilitySpec]:
    """Menace
    When this creature enters, each player sacrifices a creature of their
    choice.
    Whenever a player sacrifices a permanent, put a +1/+1 counter on this
    creature."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("sacrifice", {"selector": "each_player", "what": "creature",
                                      "count": 1})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {})],
            trigger={"event": EventType.SACRIFICE},
        ),
    ]


register("Merchant of Venom", _merchant_of_venom)
