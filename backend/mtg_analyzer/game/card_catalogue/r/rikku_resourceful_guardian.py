from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _rikku_resourceful_guardian() -> list[AbilitySpec]:
    """Whenever you put one or more counters on a creature, until end of turn, that creature can't be blocked by creatures your opponents control.
    Steal — {1}, {T}: Move a counter from target creature an opponent controls onto target creature you control. Activate only as a sorcery.

    — PLAY-ALL (Counter Blitz). The trigger is the Hapatra `COUNTER` shape (``by_you``) whose body is `unblockable` aimed at the recipient
    through `trigger_subject_referent` (the COUNTER event's ``target_id``). **Simplification:** the creature can't be blocked at all this
    turn (when the recipient is an opponent's creature it was never blockable by creatures *you* control anyway). Steal is Nesting
    Grounds' `move_counters` from a creature an opponent controls onto one you control (the controller chooses the counter kind).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("trigger_subject_referent", {"event_key": "target_id", "effects": [
                {"type": "unblockable", "params": {"target_kind": "creature"}},
            ]})],
            trigger={"event": EventType.COUNTER, "filter": {"recipient_is_creature": True, "by_you": True}},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("move_counters", {
                "source_target_kind": "creature_you_dont_control", "choose_kind": True, "dest_target_kind": "creature_you_control",
            })],
            cost={"text": "{1}, {T}", "sorcery_speed_only": True},
        ),
    ]


register("Rikku, Resourceful Guardian", _rikku_resourceful_guardian)
