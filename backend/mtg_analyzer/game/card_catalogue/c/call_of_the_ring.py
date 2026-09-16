from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _call_of_the_ring() -> list[AbilitySpec]:
    """At the beginning of your upkeep, the Ring tempts you.
    Whenever you choose a creature as your Ring-bearer, you may pay 2
    life. If you do, draw a card.

    Simplified: the second ability isn't modeled — no event fires for
    "you choose a creature as your Ring-bearer" yet (RULE 701.52a's
    choice is a `pending_choice`, not a broadcast `GameEvent`), so there's
    nothing to trigger off. The upkeep Ring-tempts-you line (this card's
    real recurring value) is fully modeled.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("the_ring_tempts_you", {})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"}, "phase_relation": "you"},
        ),
    ]


register("Call of the Ring", _call_of_the_ring)
