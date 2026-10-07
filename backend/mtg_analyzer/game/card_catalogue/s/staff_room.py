from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _staff_room() -> list[AbilitySpec]:
    """Whenever a creature you control deals combat damage to a player, turn that creature face up or put a +1/+1 counter on it.
    (You may cast either half. That door unlocks on the battlefield. As a sorcery, you may pay the mana cost of a locked door to unlock it.)

    — MEC-111, the right door of Experimental Lab // Staff Room (`game/rooms.py` binds it only while that door is unlocked). The group
    combat-damage head is the parser's (`trigger_subject_key: __group_subject__`, "that creature"); the "or" is a modal choice between
    `turn_face_up_chosen` on the firing creature (an effect, so no cost, RULE 708.8; a no-op when it is already face up) and the counter.
    """
    return [
        AbilitySpec(
            "triggered",
            [],
            trigger={
                "event": "DAMAGE",
                "condition": {"subject": "group", "controller": "you", "other": False, "filter": {"card_type": "creature"}},
                "filter": {"combat": True, "is_player": True},
            },
            modes={
                "choose": 1,
                "options": [
                    [EffectSpec("turn_face_up_chosen", {"trigger_subject_key": "__group_subject__"})],
                    [EffectSpec("add_counters", {"count": 1, "kind": "+1/+1", "trigger_subject_key": "__group_subject__"})],
                ],
                "descriptions": ["Dieses Wesen aufdecken.", "Ein +1/+1-Marker auf es legen."],
            },
        ),
    ]


register("Staff Room", _staff_room)
