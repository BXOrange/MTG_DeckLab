from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _aethertide_whale() -> list[AbilitySpec]:
    """Flying
    When this creature enters, you get six {E} (energy counters).
    Pay {E}{E}{E}{E}: Return this creature to its owner's hand.

    — PLAY-ALL (Living Energy). Flying is the keyword's; the ETB is Aether Chaser's `add_player_counters`; the
    energy-cost bounce is the parser's own `return_to_hand` over a self target.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_player_counters", {"amount": 6, "kind": "energy"})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("return_to_hand", {"target_kind": None})],
            cost={"text": "pay {e}{e}{e}{e}"},
        ),
    ]


register("Aethertide Whale", _aethertide_whale)
