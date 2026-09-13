"""PAR-50 — static combat-damage assignment replacements."""

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import MODELED, parse_oracle


def _creature(name, power, toughness, text=""):
    return Card(id=name, name=name, type_line="Creature — Beast", is_creature=True,
                power=power, toughness=toughness, oracle_text=text)


def test_par50_statics_parse():
    for text in (
        "You may have Lone Wolf assign its combat damage as though it weren't blocked.",
        "Each creature you control assigns combat damage equal to its toughness rather than its power.",
    ):
        assert parse_oracle(_creature("Lone Wolf", 2, 4, text)).coverage == MODELED


def test_as_unblocked_assignment_sends_blocked_attackers_damage_to_defender():
    attacker_card = _creature("Lone Wolf", 3, 3,
        "You may have Lone Wolf assign its combat damage as though it weren't blocked.")
    blocker_card = _creature("Blocker", 1, 5)
    engine = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_hand=0)
    attacker = GameObject(attacker_card, owner_id="p1", controller_id="p1", zone=Zone.BATTLEFIELD)
    blocker = GameObject(blocker_card, owner_id="p2", controller_id="p2", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(attacker)
    engine.state.add_to_battlefield(attacker)
    engine.state.add_to_battlefield(blocker)
    engine.recompute_continuous_effects()
    assert attacker._combat_restrictions == [{"kind": "damage_as_unblocked"}]
    attacker.attacking = True
    attacker.combat_defender = {"kind": "player", "id": "p2"}
    attacker.blocked_by = [blocker.instance_id]
    engine._deal_combat_damage_step(first_strike_step=False)
    assert engine.state.player_by_id("p2").life == 37
    assert blocker.damage_marked == 0


def test_toughness_assignment_uses_derived_toughness():
    doran = _creature("Doran", 0, 5,
        "Each creature you control assigns combat damage equal to its toughness rather than its power.")
    attacker_card = _creature("Wall", 1, 4)
    engine = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_hand=0)
    source = GameObject(doran, owner_id="p1", controller_id="p1", zone=Zone.BATTLEFIELD)
    attacker = GameObject(attacker_card, owner_id="p1", controller_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(source)
    engine.state.add_to_battlefield(source)
    engine.state.add_to_battlefield(attacker)
    engine.recompute_continuous_effects()
    assert attacker._combat_restrictions == [{"kind": "damage_uses_toughness"}]
    attacker.attacking = True
    attacker.combat_defender = {"kind": "player", "id": "p2"}
    engine._deal_combat_damage_step(first_strike_step=False)
    assert engine.state.player_by_id("p2").life == 36
