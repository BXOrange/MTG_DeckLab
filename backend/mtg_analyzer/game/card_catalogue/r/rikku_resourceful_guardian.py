from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _rikku_resourceful_guardian() -> list[AbilitySpec]:
    """Whenever you put one or more counters on a creature, until end of turn, that creature can't be blocked by creatures your opponents control.
    Steal — {1}, {T}: Move a counter from target creature an opponent controls onto target creature you control. Activate only as a sorcery.

    — PLAY-ALL (Counter Blitz). The COUNTER trigger grants a temporary
    restriction on blockers controlled by the trigger controller's opponents,
    including when the recipient is another player's creature. Steal offers
    a counter-kind choice and moves it onto a creature you control.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("trigger_subject_referent", {"event_key": "target_id", "effects": [
                {"type": "unblockable", "params": {"target_kind": "creature", "opponents_only": True}},
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
