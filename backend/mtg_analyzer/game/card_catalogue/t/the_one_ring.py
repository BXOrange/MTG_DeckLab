from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _the_one_ring() -> list[AbilitySpec]:
    """Indestructible
    When The One Ring enters, if you cast it, you gain protection from
    everything until your next turn.
    At the beginning of your upkeep, you lose 1 life for each burden
    counter on The One Ring.
    {T}: Put a burden counter on The One Ring, then draw a card for each
    burden counter on The One Ring.

    Simplified: the ETB "if you cast it" protection-from-everything grant
    isn't modeled (no "if this was cast, not put onto the battlefield
    another way" condition exists, and no generic "protection from
    everything" grant primitive) — the burden-counter draw engine/life-
    loss loop (this card's real ongoing engine) is fully modeled.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("lose_life", {"amount_from_count_selector": "burden_counters_on_self"})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"}, "phase_relation": "you"},
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("add_counters", {"kind": "burden", "amount": 1}),
                EffectSpec("draw", {"count_selector": "burden_counters_on_self"}),
            ],
            cost={"taps_self": True},
        ),
    ]


register("The One Ring", _the_one_ring)
