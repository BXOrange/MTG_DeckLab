"""PAR-117 — group attacks "you or a planeswalker you control".

RULE 508.1b has the attacker choose a player, planeswalker, or battle. The
parser must claim exactly the player-or-planeswalker spelling, while the
engine must use the attacked planeswalker's controller as the defending player
for this trigger without accidentally treating a battle as a planeswalker.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import _trigger_condition
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH


def _db():
    return CardDatabase(DEFAULT_DB_PATH)


def _engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", []), ("p3", "Carol", [])],
        starting_life=20, starting_hand=0,
    )
    eng.begin_turn()
    eng.state.current_step = "declare_attackers"
    return eng, eng.state


def _permanent(card: Card, controller: str) -> GameObject:
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.controller_id = controller
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    return obj


def _creature(controller="p2"):
    return _permanent(
        Card(id="bear", name="Bear", type_line="Creature — Bear", is_creature=True,
             power=2, toughness=2),
        controller,
    )


def _planeswalker(controller: str, name="Walker"):
    return _permanent(
        Card(id=name, name=name, type_line="Planeswalker — Test", loyalty=4), controller
    )


def test_condition_uses_a_distinct_player_or_planeswalker_scope():
    assert _trigger_condition("a creature attacks you or a planeswalker you control") == {
        "subject": "group", "type": "creature", "controller": "any",
        "other": False, "attacks_you_or_planeswalker": True,
    }


def test_real_cards_become_modeled():
    for name in (
        "Blood Reckoning", "Isperia, Supreme Judge", "Revenge of Ravens",
        "Riddlekeeper", "Search the Premises",
    ):
        result = parse_oracle(_db().get_card(name))
        assert result.modeled, (name, result.unclaimed)


def _attack_and_resolve(defender):
    eng, state = _engine()
    # Alice is active and attacks Bob, who controls Blood Reckoning and the
    # first planeswalker. A different Carol-owned planeswalker is the
    # negative control.
    source = _permanent(_db().get_card("Blood Reckoning"), "p2")
    attacker = _creature("p1")
    state.add_to_battlefield(source)
    state.add_to_battlefield(attacker)
    if isinstance(defender, GameObject):
        state.add_to_battlefield(defender)
    eng.declare_attackers(state.active_player, [{"attacker": attacker, "defender": defender}])
    placed = eng.rules.put_triggers_on_stack()
    if placed:
        eng.rules.resolve_top_of_stack()
    return state, placed


def test_blood_reckoning_fires_for_its_controllers_planeswalker():
    state, placed = _attack_and_resolve(_planeswalker("p2"))
    assert placed == 1
    assert state.player_by_id("p1").life == 19


def test_blood_reckoning_still_fires_for_its_controller_directly():
    state, placed = _attack_and_resolve({"kind": "player", "id": "p2", "label": "Bob"})
    assert placed == 1
    assert state.player_by_id("p1").life == 19


def test_blood_reckoning_does_not_fire_for_another_players_planeswalker():
    state, placed = _attack_and_resolve(_planeswalker("p3"))
    assert placed == 0
    assert state.player_by_id("p1").life == 20
