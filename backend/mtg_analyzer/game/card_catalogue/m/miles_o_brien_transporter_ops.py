from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _miles_o_brien_transporter_ops() -> list[AbilitySpec]:
    """When Miles O'Brien enters, return up to one other target creature or artifact you control to its owner's hand.
    At the beginning of each end step, if a permanent was returned to your hand from the battlefield this turn, draw a card.

    RULE 603.4 intervening "if", read from the turn's event log
    (``event_this_turn`` over ``RETURNED_TO_HAND`` from the battlefield,
    RULE 603.6c) so it also counts Miles's own enter trigger.
    """
    returned_this_turn = {
        "kind": "event_this_turn", "min": 1,
        "trigger": {
            "event": "RETURNED_TO_HAND",
            "condition": {"subject": "group", "controller": "you", "other": False},
            "filter": {"from_zone": "battlefield"},
        },
    }
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("return_to_hand", {
                "target_kind": "artifact_or_creature_you_control", "optional": True, "excludes_source": True,
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1}, condition=dict(returned_this_turn))],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"}, "active_if": dict(returned_this_turn)},
        ),
    ]


register("Miles O'Brien, Transporter Ops", _miles_o_brien_transporter_ops)
