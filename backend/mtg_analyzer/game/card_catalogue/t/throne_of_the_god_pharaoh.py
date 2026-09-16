from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _throne_of_the_god_pharaoh() -> list[AbilitySpec]:
    """At the beginning of your end step, each opponent loses life equal
    to the number of tapped creatures you control.

    — Eliferate deck batch. `LoseLifeEffect`'s new `amount_from_count_
    selector` (the `GainLifeEffect` sibling it never had) reading the new
    `tapped_creatures_you_control` count (`continuous.count_selector`).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("lose_life", {
                "selector": "each_opponent", "amount_from_count_selector": "tapped_creatures_you_control",
            })],
            trigger={
                "event": EventType.STEP_BEGIN, "filter": {"step": "end"},
                "phase_relation": "you",
            },
        ),
    ]


register("Throne of the God-Pharaoh", _throne_of_the_god_pharaoh)
