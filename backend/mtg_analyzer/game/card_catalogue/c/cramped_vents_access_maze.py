from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.catalogue.player_event_head import THIS_DOOR
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _cramped_vents_access_maze() -> list[AbilitySpec]:
    """When you unlock this door, this Room deals 6 damage to target creature an opponent controls. You gain life equal to the excess damage dealt this way.
    (You may cast either half. That door unlocks on the battlefield. As a sorcery, you may pay the mana cost of a locked door to unlock it.)

    — PLAY-ALL (Miracle Worker). The damage payoff uses the target's
    remaining lethal damage and actual damage after prevention/replacements,
    including deathtouch (RULE 120.9). The left door's text (`game/rooms.py`, MEC-111).
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("damage", {"amount": 6, "target_kind": "creature_you_dont_control"}),
                EffectSpec("gain_life", {"amount": {"kind": "this_way", "tally": "excess_damage_this_way"}}),
            ],
            trigger={"event": EventType.DOOR_UNLOCKED, "condition": {"subject": "self"}, "filter": {"door": THIS_DOOR}},
        ),
    ]


register("Cramped Vents", _cramped_vents_access_maze)
