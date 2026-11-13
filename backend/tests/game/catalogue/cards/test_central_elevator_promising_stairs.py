"""Central Elevator's name-filtered tutor and Promising Stairs' upkeep."""
import pytest

from mtg_analyzer.game import rooms
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, cast, game


NAME = "Central Elevator // Promising Stairs"
OTHER = "Walk-In Closet // Forgotten Cellar"


def _search(doors=(rooms.LEFT,), owner="p1"):
    engine = game()
    controlled = card(engine, OTHER, player=owner)
    rooms.set_designations(controlled, doors)
    same = card(engine, NAME, zone=Zone.LIBRARY)
    other = card(engine, OTHER, zone=Zone.LIBRARY)
    different = card(engine, "Grand Entryway // Elegant Rotunda", zone=Zone.LIBRARY)
    source = card(engine, NAME, zone=Zone.HAND)
    cast(engine, source)
    assert engine.state.pending_choice["kind"] == "search"
    return engine, source, same, other, different


def test_search_excludes_shared_name_with_either_unlocked_half_and_reveals_hit():
    engine, source, same, other, different = _search()
    choice = engine.state.pending_choice
    ids = {option.get("instance_id") for option in choice["options"]}
    assert same.instance_id not in ids and other.instance_id not in ids and different.instance_id in ids
    engine.resolve_pending_choice(str(different.instance_id))
    engine.resolve_until_stable()
    assert different.zone == Zone.HAND
    assert any(event.type == EventType.REVEAL and event.get("instance_id") == different.instance_id
               for event in engine.state.events_this_turn())
    assert any(event.type == EventType.SHUFFLE for event in engine.state.events_this_turn())


@pytest.mark.parametrize("doors,owner", [((), "p1"), ((rooms.LEFT,), "p2")])
def test_nameless_locked_room_or_opponents_room_does_not_exclude_library_copy(doors, owner):
    engine, source, same, other, different = _search(doors, owner)
    assert other.instance_id in {option.get("instance_id") for option in engine.state.pending_choice["options"]}


def test_right_unlocked_name_also_excludes_library_room():
    engine, source, same, other, different = _search((rooms.RIGHT,))
    assert other.instance_id not in {option.get("instance_id") for option in engine.state.pending_choice["options"]}


def test_search_choice_survives_clone_and_may_fail_to_find():
    engine, source, same, other, different = _search()
    clone = GameEngine(engine.state.clone())
    clone.resolve_pending_choice(str(different.instance_id))
    clone.resolve_until_stable()
    assert clone.state.find_object(different.instance_id).zone == Zone.HAND
    engine.resolve_pending_choice("decline")
    engine.resolve_until_stable()
    assert different.zone == Zone.LIBRARY
    assert any(event.type == EventType.SHUFFLE for event in engine.state.events_this_turn())


@pytest.mark.parametrize("eighth_name", [False, True])
def test_stairs_surveils_and_requires_eight_distinct_unlocked_names(eighth_name):
    engine = game()
    source = card(engine, NAME, zone=Zone.HAND)
    cast(engine, source, face="back")
    for name in (OTHER, "Grand Entryway // Elegant Rotunda", "Meat Locker // Drowned Diner"):
        obj = card(engine, name)
        rooms.set_designations(obj, rooms.DOORS)
    if eighth_name:
        obj = card(engine, "Glassworks // Shattered Yard")
        rooms.set_designations(obj, [rooms.LEFT])
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep"))
    engine.resolve_until_stable()
    assert engine.state.pending_choice["kind"] == "surveil"
    engine.resolve_pending_choice("decline")
    engine.resolve_until_stable()
    assert engine.state.winner_id == ("p1" if eighth_name else None)
