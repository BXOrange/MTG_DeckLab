"""PAR-117 — Curse Auras attach to players and see attacks against them."""

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


def _attacker():
    obj = GameObject(
        Card(id="bear", name="Bear", type_line="Creature — Bear", is_creature=True,
             power=2, toughness=2),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    obj.controller_id = "p1"
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    return obj


def test_enchanted_player_attack_condition_is_explicit():
    assert _trigger_condition("a creature attacks enchanted player") == {
        "subject": "group", "type": "creature", "controller": "any", "other": False,
        "attacks_enchanted_player": True,
    }


def test_curse_of_the_forsaken_is_modeled():
    result = parse_oracle(_db().get_card("Curse of the Forsaken"))
    assert result.modeled, result.unclaimed


def test_curse_attaches_to_player_and_only_triggers_for_that_players_attackers():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", []), ("p3", "Carol", [])],
        starting_life=20, starting_hand=0,
    )
    state, p1, p2, p3 = eng.state, *eng.state.players
    curse = GameObject(_db().get_card("Curse of the Forsaken"), owner_id=p1.id, zone=Zone.HAND)
    curse.controller_id = p1.id
    bind_from_catalogue(curse)
    p1.add_to_zone(curse, Zone.HAND)
    p1.mana_pool.add_many({"W": 1, "C": 2})
    eng.begin_turn()
    state.current_step = "main1"
    eng.cast_spell(p1, curse, targets=[p2])
    eng.resolve_until_stable()
    assert curse in state.battlefield
    assert curse.attached_to == p2.id

    attacker = _attacker()
    state.add_to_battlefield(attacker)
    eng.begin_turn()
    state.active_player_index = 0
    state.current_step = "declare_attackers"
    eng.declare_attackers(p1, [{"attacker": attacker, "defender": p2}])
    assert eng.rules.put_triggers_on_stack() == 1
    eng.rules.resolve_top_of_stack()
    assert p1.life == 21

    # A later combat against Carol must not use the Aura controller or the
    # attacker controller as a substitute for the actual enchanted player.
    attacker.attacking = False
    attacker.tapped = False
    state.current_step = "declare_attackers"
    eng.declare_attackers(p1, [{"attacker": attacker, "defender": p3}])
    assert eng.rules.put_triggers_on_stack() == 0
