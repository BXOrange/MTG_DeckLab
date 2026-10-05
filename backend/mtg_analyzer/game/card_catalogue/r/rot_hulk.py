from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _rot_hulk() -> list[AbilitySpec]:
    """Menace
    When this creature enters, return up to X target Zombie cards from your graveyard to the battlefield, where X is the number of opponents you have.

    — PLAY-ALL Step 2 (Eternal Might). Menace is a printed keyword. `return_from_graveyard` over the new
    ``graveyard_zombie_card`` target kind, "up to" `TargetSpec.count_selector: "opponents"` (the shipped opponents
    count read as the ability is announced).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("return_from_graveyard", {
                "target_kind": "graveyard_zombie_card", "destination": "battlefield",
                "count_selector": "opponents", "optional": True,
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Rot Hulk", _rot_hulk)
