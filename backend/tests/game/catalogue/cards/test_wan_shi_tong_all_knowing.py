"""Wan Shi Tong's owner-selected library position and library-arrival trigger."""
import pytest

from mtg_analyzer.game import combat
from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.catalogue import battlefield_object
from tests.support.star_trek import cast, game, on_battlefield, stock_library, vanilla


def _entry_choice(engine, p1, victim):
    owl = p1.hand[0]
    cast(engine, p1, owl)
    choice = engine.state.pending_choice
    assert choice["kind"] == "trigger_target"
    engine.resolve_pending_choice(str(victim.instance_id))
    engine.resolve_until_stable()
    choice = engine.state.pending_choice
    assert choice["kind"] == "library_position"
    assert choice["player_id"] == victim.owner_id
    assert choice["top_depth"] == 2
    return owl


@pytest.mark.parametrize("position", ["top", "bottom"])
def test_owner_chooses_position_and_library_arrival_makes_two_spirits(position):
    engine, p1, p2 = game("Wan Shi Tong, All-Knowing")
    library = stock_library(engine, "p2", 3)
    victim = vanilla(engine, "p2")
    victim.controller_id = "p1"  # the owner, rather than the controller, decides
    owl = _entry_choice(engine, p1, victim)
    assert combat.has(owl, "flying")
    assert len(owl.triggered_abilities) == 2
    a, b = specs_for(owl.card), specs_for(owl.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    engine.resolve_pending_choice(position)
    engine.resolve_until_stable()
    expected = [library[0], library[1], victim, library[2]] if position == "top" else [victim, *library]
    assert p2.library == expected and victim.zone == Zone.LIBRARY
    spirits = [obj for obj in engine.state.permanents() if obj.is_token]
    assert len(spirits) == 2
    assert all(obj.controller_id == "p1" and obj.power == obj.toughness == 1 for obj in spirits)
    assert all("Spirit" in obj.card.type_line for obj in spirits)
    bear = vanilla(engine, "p2", "Non-Spirit")
    spirit = vanilla(engine, "p2", "Other Spirit")
    spirit.card.type_line = "Creature — Spirit"
    engine.recompute_continuous_effects()
    assert not combat.blocker_allowed(spirits[0], bear, engine.state)
    assert not combat.blocker_may_block(spirits[0], bear)
    assert combat.blocker_allowed(spirits[0], spirit, engine.state)
    assert combat.blocker_may_block(spirits[0], spirit)


@pytest.mark.parametrize("library_size", [0, 1])
def test_second_from_top_handles_short_library_and_choice_survives_clone(library_size):
    engine, p1, p2 = game("Wan Shi Tong, All-Knowing")
    library = stock_library(engine, "p2", library_size)
    victim = vanilla(engine, "p2")
    _entry_choice(engine, p1, victim)
    clone = GameEngine(engine.state.clone())
    clone.resolve_pending_choice("top")
    clone.resolve_until_stable()
    actual = clone.state.player_by_id("p2").library
    assert [obj.instance_id for obj in actual] == [victim.instance_id, *[obj.instance_id for obj in library]]
    assert victim.zone == Zone.BATTLEFIELD  # original game is untouched


def test_etb_target_pool_excludes_lands():
    engine, p1, p2 = game("Wan Shi Tong, All-Knowing")
    land = battlefield_object(engine, "p2", "Forest", "Basic Land — Forest", is_land=True)
    cast(engine, p1, p1.hand[0])
    choice = engine.state.pending_choice
    assert choice["kind"] == "trigger_target"
    assert str(land.instance_id) not in [str(option["id"]) for option in choice["options"]]


def test_multiple_cards_in_one_library_batch_trigger_once_but_reordering_does_not():
    engine, p1, p2 = game()
    on_battlefield(engine, "p1", "Wan Shi Tong, All-Knowing")
    first = vanilla(engine, "p2", "First")
    second = vanilla(engine, "p2", "Second")
    engine.state.hold_batches()
    engine.rules.return_to_library(first)
    engine.rules.return_to_library(second)
    engine.state.release_batches()
    engine.resolve_until_stable()
    assert len([obj for obj in engine.state.permanents() if obj.is_token]) == 2
    engine.rules.return_to_library(first, "bottom")
    engine.resolve_until_stable()
    assert len([obj for obj in engine.state.permanents() if obj.is_token]) == 2
