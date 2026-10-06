from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _bottomless_pool_locker_room() -> list[AbilitySpec]:
    """When you unlock this door, return up to one target creature to its owner's hand.
    (You may cast either half. That door unlocks on the battlefield. As a sorcery, you may pay the mana cost of a locked door to unlock it.)

    — PLAY-ALL (Miracle Worker). `return_to_hand` over an optional creature target on an enters trigger. **Simplification (as in Experimental Lab // Staff Room):** Rooms have no door state in the engine, so casting the Room is its
    door unlocking — the ability is an enters trigger — and the cache holds only this front door's text.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("return_to_hand", {"target_kind": "creature", "optional": True})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Bottomless Pool // Locker Room", _bottomless_pool_locker_room)
register("Bottomless Pool", _bottomless_pool_locker_room)
