from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _yedora_grave_gardener() -> list[AbilitySpec]:
    """Whenever another nontoken creature you control dies, you may return it to the battlefield face down under its owner's control. It's a Forest land. (It has no other types or abilities.)

    — PLAY-ALL (Jump Scare!). An optional DIES group trigger over `return_from_graveyard` of the dying card
    (``trigger_subject_key: instance_id``, only while it is still in a graveyard) with the new ``face_down_as:
    forest_land`` — the card is turned face down as a `face_down.LAND_KINDS` Forest before it enters (RULE 708.3), so it
    is a land with only the basic land type's mana ability, and cannot be turned face up.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("return_from_graveyard", {
                "destination": "battlefield", "trigger_subject_key": "instance_id", "face_down_as": "forest_land",
            })],
            trigger={"event": EventType.DIES, "condition": {
                "subject": "group", "controller": "you", "other": True,
                "filter": {"nontoken": True, "card_type": "creature"},
            }},
            optional=True,
        ),
    ]


register("Yedora, Grave Gardener", _yedora_grave_gardener)
