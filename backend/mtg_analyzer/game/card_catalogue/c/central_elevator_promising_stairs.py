"""Central Elevator // Promising Stairs."""
from ....models.game.events import EventType
from ....parser.oracle.catalogue.player_event_head import THIS_DOOR
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _central_elevator():
    """When you unlock this door, search your library for a Room card that doesn't have the same name as a Room you control, reveal it, put it into your hand, then shuffle."""
    return [AbilitySpec("triggered", [EffectSpec("search_different_room_name", {})], trigger={
        "event": EventType.DOOR_UNLOCKED, "condition": {"subject": "self"}, "filter": {"door": THIS_DOOR},
    })]


def _promising_stairs():
    """At the beginning of your upkeep, surveil 1. You win the game if there are eight or more different names among unlocked doors of Rooms you control."""
    return [AbilitySpec("triggered", [
        EffectSpec("surveil", {"count": 1}),
        EffectSpec("win_game", {}, condition={"kind": "control_count", "selector": {
            "zone": "battlefield", "of": "you", "filter": {"subtype": "room"}, "distinct": "door_name",
        }, "min": 8}),
    ], trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"}, "phase_relation": "you"})]


register("Central Elevator", _central_elevator)
register("Promising Stairs", _promising_stairs)
