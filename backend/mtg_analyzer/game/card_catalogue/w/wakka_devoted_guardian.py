from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _wakka_devoted_guardian() -> list[AbilitySpec]:
    """Reach, trample
    Whenever Wakka deals combat damage to a player, destroy up to one target artifact that player controls and put a +1/+1 counter on Wakka.
    Blitzball Captain — At the beginning of your end step, if a counter was put on Wakka this turn, put a +1/+1 counter on each other
    creature you control.

    — PLAY-ALL (Counter Blitz). Reach and trample are keywords. The damage trigger is the parser's own claim. The end-step trigger is a
    RULE 603.4 intervening-if on the new ``counter_put_on_source_this_turn`` condition (a positive `COUNTER` event on Wakka this turn) over
    `add_counters` on the structured group of other creatures you control (``group_other``).
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("destroy", {"target_kind": "artifact_that_player_controls", "optional": True}),
                EffectSpec("add_counters", {"count": 1, "kind": "+1/+1"}),
            ],
            trigger={"event": EventType.DAMAGE, "condition": {"subject": "self"}, "filter": {"combat": True, "is_player": True}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {
                "count": 1, "kind": "+1/+1", "group_other": True,
                "group": {"zone": "battlefield", "of": "you", "filter": {"card_type": "creature"}},
            })],
            trigger={
                "event": EventType.STEP_BEGIN, "filter": {"step": "end"}, "phase_relation": "you",
                "active_if": {"kind": "counter_put_on_source_this_turn"},
            },
        ),
    ]


register("Wakka, Devoted Guardian", _wakka_devoted_guardian)
