"""PAR-117 — a group-trigger's bare ``it`` can be the firing creature."""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH


def _db():
    return CardDatabase(DEFAULT_DB_PATH)


def _creature(name, controller, power):
    obj = GameObject(
        Card(id=name, name=name, type_line="Creature — Human", is_creature=True,
             power=power, toughness=2),
        owner_id=controller, zone=Zone.BATTLEFIELD,
    )
    obj.controller_id = controller
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    return obj


def test_maccready_becomes_modeled():
    result = parse_oracle(_db().get_card("MacCready, Lamplight Mayor"))
    assert result.modeled, result.unclaimed


def test_maccready_grants_skulk_to_the_small_attacker_not_himself():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    state = eng.state
    mayor = GameObject(_db().get_card("MacCready, Lamplight Mayor"), owner_id="p1", zone=Zone.BATTLEFIELD)
    mayor.controller_id = "p1"
    bind_from_catalogue(mayor)
    attacker = _creature("Small attacker", "p1", 2)
    state.add_to_battlefield(mayor)
    state.add_to_battlefield(attacker)
    eng.begin_turn()
    state.current_step = "declare_attackers"
    eng.declare_attackers(state.active_player, [attacker])
    assert eng.rules.put_triggers_on_stack() == 1
    eng.rules.resolve_top_of_stack()
    assert "skulk" in attacker.temp_keywords
    assert "skulk" not in mayor.temp_keywords
