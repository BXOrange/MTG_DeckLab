from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _the_reaper_king_no_more() -> list[AbilitySpec]:
    """When The Reaper enters, put a -1/-1 counter on each of up to two
    target creatures.
    Whenever a creature an opponent controls with a -1/-1 counter on it
    dies, you may put that card onto the battlefield under your control.
    Do this only once each turn.

    Registered wholesale (so the parser is skipped), so both clauses are
    authored: the ETB as an ordinary ``add_counters`` "each of up to two
    target creatures" triggered ability, the dies trigger as Necroskitter's
    group DIES trigger plus the action-limit marker ("Do this only once each
    turn" -- limits the action, not the trigger).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {
                "count": 1, "kind": "-1/-1", "target_kind": "creature",
                "target_count": 2, "optional": True,
            })],
            trigger={"event": "ENTERS_BATTLEFIELD", "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [
                EffectSpec("trigger_subject_referent", {
                    "event_key": "__group_subject__",
                    "effects": [{"type": "return_from_graveyard", "params": {
                        "target_kind": "any_graveyard_card", "destination": "battlefield",
                        "under_your_control": True,
                    }}],
                }),
                # PAR-135: "Do this only once each turn." limits the action, not the trigger.
                EffectSpec("action_once_per_turn_marker", {}),
            ],
            trigger={"event": "DIES", "condition": {
                "subject": "group", "controller": "not_you", "other": False,
                "type": "creature", "has_counter_kind": "-1/-1",
            }},
            optional=True,
        ),
    ]


register("The Reaper, King No More", _the_reaper_king_no_more)
