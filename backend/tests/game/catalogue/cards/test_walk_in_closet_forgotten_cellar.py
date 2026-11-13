"""Independent Room doors, graveyard casting and the turn-scoped exile redirect."""
from mtg_analyzer.game import rooms
from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import RICH, card, cast, filler, game


NAME = "Walk-In Closet // Forgotten Cellar"


def _board(face="back"):
    engine = game()
    player = engine.state.player_by_id("p1")
    room = card(engine, NAME, zone=Zone.HAND)
    bear = card(engine, "Grizzly Bears", zone=Zone.GRAVEYARD)
    land = card(engine, "Forest", zone=Zone.GRAVEYARD)
    cast(engine, room, face=face)
    return engine, player, room, bear, land


def test_right_door_casts_spells_but_does_not_allow_graveyard_lands():
    engine, player, room, bear, land = _board()
    assert room.unlocked_doors == {rooms.RIGHT}
    assert len(room.triggered_abilities) == 1
    assert engine.can_cast(player, bear) and not engine.can_play_land(player, land)
    cast(engine, bear)
    assert bear.zone == Zone.BATTLEFIELD
    engine.rules.destroy(bear)
    assert bear.zone == Zone.EXILE


def test_left_door_plays_lands_without_granting_spell_casting_or_exile_redirect():
    engine, player, room, bear, land = _board("front")
    assert room.unlocked_doors == {rooms.LEFT}
    assert not engine.can_cast(player, bear) and engine.can_play_land(player, land)
    engine.play_land(player, land)
    assert land.zone == Zone.BATTLEFIELD
    engine.rules.destroy(land)
    assert land.zone == Zone.GRAVEYARD


def test_right_door_unlocked_after_casting_left_grants_permission_and_redirect():
    engine, player, room, bear, land = _board("front")
    player.mana_pool.add_many(RICH)
    engine.unlock_door(player, room, rooms.RIGHT)
    engine.resolve_until_stable()
    assert room.unlocked_doors == {rooms.LEFT, rooms.RIGHT}
    assert engine.can_cast(player, bear) and engine.can_play_land(player, land)
    # The replacement covers every owned card heading to the graveyard, not just spells cast with permission.
    other = filler(engine, "Other", power=2, toughness=2)
    engine.rules.destroy(other)
    assert other.zone == Zone.EXILE


def test_permission_survives_locking_and_source_removal_and_expires_next_turn():
    engine, player, room, bear, land = _board()
    assert rooms.lock(engine.state, room, rooms.RIGHT)
    engine.recompute_continuous_effects()
    assert engine.can_cast(player, bear)
    engine.rules.exile(room)
    assert engine.can_cast(player, bear)
    engine.state.internal_turn.number += 1
    assert not engine.can_cast(player, bear)
    other = filler(engine, "Other", power=2, toughness=2)
    engine.rules.destroy(other)
    assert other.zone == Zone.GRAVEYARD


def test_cloned_turn_permission_casts_spell_and_exiles_it_after_resolution():
    engine, player, room, bear, land = _board()
    spell = card(engine, "Giant Growth", zone=Zone.GRAVEYARD)
    target = filler(engine, "Target", power=2, toughness=2)
    clone = GameEngine(engine.state.clone())
    cast(clone, clone.state.find_object(spell.instance_id), targets=[clone.state.find_object(target.instance_id)])
    assert clone.state.find_object(spell.instance_id).zone == Zone.EXILE
    assert clone.state.find_object(target.instance_id).power == 5
    assert spell.zone == Zone.GRAVEYARD and target.power == 2


def test_factories_return_independent_specs_for_both_doors():
    engine, player, room, bear, land = _board()
    for door in rooms.DOORS:
        face = rooms.door_card(room.card, door)
        a, b = specs_for(face), specs_for(face)
        assert a and a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
