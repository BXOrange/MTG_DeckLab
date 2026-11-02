"""The Undercity's bottom room uses a revealed, bounded library choice."""
import pytest

from mtg_analyzer.game import dungeons
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.models.game.game_object import GameObject, Zone


def _room_game(creatures=True, count=12):
    engine = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_hand=0)
    player = engine.state.players[0]
    objects = []
    for i in range(count):
        creature = creatures and i in (count - 2, count - 3)
        obj = GameObject(Card(id=f"room-{i}", name=f"Card {i}",
                              type_line="Creature — Bear" if creature else "Land",
                              is_creature=creature, is_land=not creature,
                              power=2 if creature else None, toughness=2 if creature else None),
                         owner_id=player.id, zone=Zone.LIBRARY)
        player.add_to_zone(obj, Zone.LIBRARY)
        objects.append(obj)
    player.dungeon = dungeons.dungeon_by_name("Undercity")
    player.dungeon.controller_id = player.id
    player.dungeon.current_room = "Archives"
    engine.rules.venture_into_the_dungeon(player, "Undercity")
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()
    return engine, player, objects


def test_room_reveals_ten_offers_only_creatures_and_enters_with_counters():
    engine, player, objects = _room_game()
    choice = engine.state.pending_choice
    assert choice["kind"] == "choose_objects"
    assert {option["instance_id"] for option in choice["options"]} == {o.instance_id for o in objects[-3:-1]}
    reveals = [event for event in engine.state.events_this_turn() if event.type == EventType.REVEAL]
    assert {event.get("instance_id") for event in reveals} == {o.instance_id for o in objects[-10:]}
    chosen = objects[-2]
    with pytest.raises(ValueError):
        engine.rules.resolve_choice("decline")
    engine.rules.resolve_choice(str(chosen.instance_id))
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert chosen in engine.state.battlefield
    assert chosen.counters == {"+1/+1": 3}
    assert chosen.power == 5
    assert "hexproof" in chosen.granted_keywords
    assert len(player.library) == 11
    assert player.dungeon is None
    assert player.completed_dungeons
    # The duration expires at this player's next turn, rather than cleanup.
    from mtg_analyzer.game import durations
    assert any(a.duration == "your_next_turn" for a in engine.state.floating_statics)
    durations.sweep(engine.state, "cleanup")
    engine.recompute_continuous_effects()
    assert "hexproof" in chosen.granted_keywords
    durations.sweep(engine.state, "turn_begin")
    engine.recompute_continuous_effects()
    assert "hexproof" not in chosen.granted_keywords


def test_room_without_creature_reveals_and_shuffles_without_a_choice():
    engine, player, objects = _room_game(creatures=False, count=3)
    assert engine.state.pending_choice is None
    assert set(player.library) == set(objects)
    assert player.dungeon is None
    assert len([event for event in engine.state.events_this_turn() if event.type == EventType.REVEAL]) == 3


def test_authored_room_specs_are_fresh():
    room = dungeons.dungeon_by_name("Undercity").room("Throne of the Dead Three")
    first, second = dungeons.room_effect_specs(room), dungeons.room_effect_specs(room)
    first[0]["params"]["entry_counters"]["+1/+1"] = 100
    assert second[0]["params"]["entry_counters"] == {"+1/+1": 3}
