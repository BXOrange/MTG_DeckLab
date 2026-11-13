"""The Crimson Avenger: reveal in place, mandatory free cast, then shuffle."""
import pytest

from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import RICH, card, cast, filler, game, main_phase


def _trigger(engine, mana_value=2, x=0):
    p2 = engine.state.player_by_id("p2")
    target = filler(engine, "Their spell", type_line="Instant", player="p2", mv=mana_value,
                    zone=Zone.HAND, mana_cost_string="{X}{2}" if x else "{2}")
    main_phase(engine)
    p2.mana_pool.add_many(RICH)
    engine.cast_spell(p2, target, x=x)
    avenger = card(engine, "The Crimson Avenger", zone=Zone.HAND)
    cast(engine, avenger)
    choice = engine.state.pending_choice
    assert choice["kind"] == "trigger_target"
    assert len(choice["options"]) == 1
    engine.resolve_pending_choice(choice["options"][0]["id"])
    engine.resolve_until_stable()
    return avenger, target


def test_reveals_until_matching_value_then_casts_free_with_targets_and_shuffles():
    engine = game(library=0)
    p1 = engine.state.player_by_id("p1")
    bottom = filler(engine, "Unrevealed", type_line="Artifact", mv=3, zone=Zone.LIBRARY)
    hit = card(engine, "Lightning Bolt", zone=Zone.LIBRARY)
    miss = filler(engine, "Miss", type_line="Artifact", mv=7, zone=Zone.LIBRARY)
    avenger, target = _trigger(engine, mana_value=1)
    assert len(avenger.triggered_abilities) == 1
    assert specs_for(avenger.card)[0] is not specs_for(avenger.card)[0]
    choice = engine.state.pending_choice
    assert choice["kind"] == "play_during_resolution" and choice["mandatory"]
    assert choice["zone"] == "library" and choice["instance_ids"] == [hit.instance_id]
    revealed = [event.get("instance_id") for event in engine.state.events_this_turn()
                if event.type == EventType.REVEAL]
    assert revealed == [hit.instance_id, miss.instance_id]  # event iterator is newest first
    assert p1.library == [bottom, hit, miss] and not p1.exile
    p1.mana_pool.empty()
    with pytest.raises(ValueError, match="mandatory"):
        engine.resolve_pending_choice("decline")
    engine.play_resolution_card(p1, hit, targets=[engine.state.player_by_id("p2")])
    assert hit.zone == Zone.STACK
    assert set(obj.instance_id for obj in p1.library) == {bottom.instance_id, miss.instance_id}
    assert any(event.type == EventType.SHUFFLE for event in engine.state.events_this_turn())
    assert engine.state.player_by_id("p2").life == 20  # shuffle precedes the nested spell resolving
    engine.resolve_until_stable()
    assert engine.state.player_by_id("p2").life == 17
    assert target.zone == Zone.GRAVEYARD


def test_x_in_the_target_spell_counts_toward_matching_mana_value():
    engine = game(library=0)
    hit = filler(engine, "Five", type_line="Artifact", mv=5, zone=Zone.LIBRARY)
    filler(engine, "Two", type_line="Artifact", mv=2, zone=Zone.LIBRARY)
    _trigger(engine, mana_value=2, x=3)
    assert engine.state.pending_choice["instance_ids"] == [hit.instance_id]


def test_no_matching_card_reveals_entire_library_and_shuffles_without_exile():
    engine = game(library=0)
    p1 = engine.state.player_by_id("p1")
    misses = [filler(engine, f"Miss {i}", type_line="Artifact", mv=7, zone=Zone.LIBRARY) for i in range(3)]
    _trigger(engine)
    assert not engine.state.pending_choice and not p1.exile
    assert set(obj.instance_id for obj in p1.library) == {obj.instance_id for obj in misses}
    assert len([event for event in engine.state.events_this_turn() if event.type == EventType.REVEAL]) == 3
    assert any(event.type == EventType.SHUFFLE for event in engine.state.events_this_turn())


def test_matching_land_cannot_be_cast_and_remains_in_shuffled_library():
    engine = game(library=0)
    land = filler(engine, "Land", type_line="Land", mv=0, zone=Zone.LIBRARY)
    _trigger(engine, mana_value=0)
    assert engine.state.pending_choice["kind"] == "play_during_resolution"
    engine.resolve_pending_choice("decline")  # a mandatory cast is impossible
    engine.resolve_until_stable()
    assert land.zone == Zone.LIBRARY and land in engine.state.player_by_id("p1").library


def test_clone_keeps_the_pending_cast_and_following_shuffle():
    engine = game(library=0)
    hit = filler(engine, "Two", type_line="Artifact", mv=2, zone=Zone.LIBRARY)
    _trigger(engine)
    clone = GameEngine(engine.state.clone())
    cloned_hit = clone.state.find_object(hit.instance_id)
    clone.play_resolution_card(clone.state.player_by_id("p1"), cloned_hit)
    assert cloned_hit.zone == Zone.STACK and hit.zone == Zone.LIBRARY
    assert any(event.type == EventType.SHUFFLE for event in clone.state.events_this_turn())
    assert not any(event.type == EventType.SHUFFLE for event in engine.state.events_this_turn())


def test_no_opponents_spell_means_no_reveal_or_shuffle():
    engine = game(library=0)
    filler(engine, "Library card", type_line="Artifact", mv=2, zone=Zone.LIBRARY)
    avenger = card(engine, "The Crimson Avenger", zone=Zone.HAND)
    cast(engine, avenger)
    assert avenger.zone == Zone.BATTLEFIELD
    assert not engine.state.pending_choice
    assert not any(event.type in (EventType.REVEAL, EventType.SHUFFLE)
                   for event in engine.state.events_this_turn())
