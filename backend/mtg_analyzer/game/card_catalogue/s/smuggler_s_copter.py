from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _smuggler_s_copter() -> list[AbilitySpec]:
    """Flying
    Whenever this Vehicle attacks or blocks, you may draw a card. If you do, discard a card.
    Crew 1 (Tap any number of creatures you control with total power 1 or more: This Vehicle becomes an artifact creature until end of turn.)

    — PLAY-ALL (Shorikai Vehicles). Flying and Crew are keywords. The loot is an `optional` wrapper around draw-then-discard (declining
    does neither, which is what "if you do" means), on one head per event.
    """
    def loot() -> list[EffectSpec]:
        return [EffectSpec("optional", {"prompt": "Eine Karte ziehen und dann eine ablegen?", "effects": [
            {"type": "draw", "params": {"count": 1}}, {"type": "discard", "params": {"count": 1}},
        ]})]

    return [
        AbilitySpec("triggered", loot(), trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}}),
        AbilitySpec("triggered", loot(), trigger={"event": EventType.BLOCKS, "condition": {"subject": "self"}}),
    ]


register("Smuggler's Copter", _smuggler_s_copter)
