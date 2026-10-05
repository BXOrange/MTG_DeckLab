from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _lasting_tarfire() -> list[AbilitySpec]:
    """At the beginning of each end step, if you put a counter on a creature
    this turn, this enchantment deals 2 damage to each opponent.

    Authored: one triggered ability on *each* end step (no
    ``phase_relation``), with a trigger-level RULE 603.4 intervening-if
    (``active_if={"kind": "you_placed_counter_on_creature_this_turn"}``) that
    reads the new `GameState.counter_placed_on_creature_this_turn` causer
    set, populated in `RulesEngine.add_counters`.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"amount": 2, "selector": "each_opponent"})],
            trigger={
                "event": "STEP_BEGIN", "filter": {"step": "end"},
                "active_if": {"kind": "you_placed_counter_on_creature_this_turn"},
            },
        ),
    ]


register("Lasting Tarfire", _lasting_tarfire)
