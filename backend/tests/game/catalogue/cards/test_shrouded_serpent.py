"""Shrouded Serpent (hand-authored)."""

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.services.card_database import CardDatabase

NAME = 'Shrouded Serpent'


def _engine():
    eng = GameEngine.new_game([("p1", "p1", []), ("p2", "p2", [])], starting_life=20, starting_hand=0)
    eng.start()
    return eng


def _put(eng, card, controller):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.controller_id = controller
    obj.summoning_sick = False
    eng.state.add_to_battlefield(obj)
    bind_from_catalogue(obj)
    return obj


def _serpent(eng):
    return _put(eng, CardDatabase(DB_PATH).get_card(NAME), "p1")


def _blocker(eng):
    return _put(eng, Card(id="Wall", name="Wall", type_line="Creature — Wall", is_creature=True,
                          power=0, toughness=4), "p2")


def _attack(eng, serpent, defender_mana=0):
    while eng.state.current_step != "declare_attackers":
        eng.advance_step()
    # Added after the step changes: mana empties from the pool at the end of each step (RULE 500.5).
    eng.state.player_by_id("p2").mana_pool.add("C", defender_mana)
    eng.declare_attackers(eng.state.active_player, [
        {"attacker": serpent, "defender": {"kind": "player", "id": "p2"}}])
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_top_of_stack()


def test_registered_and_fresh_each_call():
    eng = _engine()
    obj = _serpent(eng)
    first, second = specs_for(obj.card), specs_for(obj.card)
    assert first and first is not second and first[0] is not second[0]
    assert [s.ability_kind for s in first] == ['triggered']


def test_binds_onto_the_object():
    eng = _engine()
    assert len(_serpent(eng).triggered_abilities) == 1


def test_end_to_end():
    # The defender can't afford {4} (the offer is skipped): the Serpent can't be blocked this turn (RULE 509.1b).
    eng = _engine()
    serpent = _serpent(eng)
    wall = _blocker(eng)
    _attack(eng, serpent)
    assert eng.state.pending_choice is None
    assert serpent.temp_unblockable
    assert not eng.can_block(eng.state.player_by_id("p2"), wall, serpent)


def test_declining_with_mana_available_still_makes_it_unblockable():
    eng = _engine()
    serpent = _serpent(eng)
    _attack(eng, serpent, defender_mana=4)
    eng.rules.resolve_choice("decline")
    assert serpent.temp_unblockable
    assert eng.state.player_by_id("p2").mana_pool.total() == 4


def test_paying_four_keeps_it_blockable():
    eng = _engine()
    serpent = _serpent(eng)
    wall = _blocker(eng)
    _attack(eng, serpent, defender_mana=4)
    choice = eng.state.pending_choice
    assert choice["player_id"] == "p2"
    eng.rules.resolve_choice("pay")
    assert eng.state.player_by_id("p2").mana_pool.total() == 0  # the {4} was spent
    assert not serpent.temp_unblockable
    assert eng.can_block(eng.state.player_by_id("p2"), wall, serpent)
