"""PAR-117 — tautological "blocks this turn" group-trigger tail."""

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


def _permanent(name, type_line, controller, *, creature=False):
    obj = GameObject(
        Card(id=name, name=name, type_line=type_line, is_creature=creature,
             power=2 if creature else None, toughness=2 if creature else None),
        owner_id=controller, zone=Zone.BATTLEFIELD,
    )
    obj.controller_id = controller
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    return obj


def test_blocks_this_turn_is_the_same_group_condition():
    assert _trigger_condition("a creature blocks this turn") == {
        "subject": "group", "type": "creature", "controller": "any", "other": False,
    }


def test_mage_hunters_onslaught_becomes_modeled():
    result = parse_oracle(_db().get_card("Mage Hunters' Onslaught"))
    assert result.modeled, result.unclaimed


def test_mage_hunters_onslaught_drains_the_blockers_controller():
    # A sorcery: "whenever a creature blocks this turn" is created when it resolves
    # (RULE 603.7a, PAR-124) — it is not an ability of a permanent.
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    state = eng.state
    spell = GameObject(_db().get_card("Mage Hunters' Onslaught"), owner_id="p1", zone=Zone.HAND)
    spell.controller_id = "p1"
    bind_from_catalogue(spell)
    state.player_by_id("p1").hand.append(spell)
    attacker = _permanent("Attacker", "Creature — Bear", "p1", creature=True)
    blocker = _permanent("Blocker", "Creature — Bear", "p2", creature=True)
    victim = _permanent("Victim", "Creature — Bear", "p2", creature=True)
    for obj in (attacker, blocker, victim):
        state.add_to_battlefield(obj)
    eng.begin_turn()
    state.current_step = "main1"
    eng.rules.cast_without_paying(state.active_player, spell, targets=[victim])
    eng.resolve_until_stable()
    assert victim not in state.battlefield
    state.current_step = "declare_attackers"
    eng.declare_attackers(state.active_player, [attacker])
    state.current_step = "declare_blockers"
    eng.declare_blockers(state.player_by_id("p2"), [{"blocker": blocker, "attacker": attacker}])
    assert eng.rules.put_triggers_on_stack() == 1
    eng.rules.resolve_top_of_stack()
    assert state.player_by_id("p2").life == 19
