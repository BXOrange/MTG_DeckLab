"""PAR-92 — replacement, meld, and commander-damage residue."""

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH


def _engine():
    return GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_hand=0)


def _db():
    return CardDatabase(DEFAULT_DB_PATH)


def test_self_graveyard_shuffle_replacement_parses_ticket_cycle():
    for name in ("Blightsteel Colossus", "Darksteel Colossus", "Legacy Weapon"):
        result = parse_oracle(_db().get_card(name))
        assert result.modeled
        static = next(spec for spec in result.specs if spec.ability_kind == "static")
        assert static.effects[0].type == "grant_graveyard_to_library_replacement"


def test_self_graveyard_shuffle_replacement_redirects_destroy():
    engine = _engine()
    obj = GameObject(_db().get_card("Blightsteel Colossus"), owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.controller_id = "p1"
    bind_from_catalogue(obj)
    engine.state.add_to_battlefield(obj)
    engine.recompute_continuous_effects()
    engine.rules.destroy(obj)
    assert obj.zone == Zone.LIBRARY


def test_triple_threat_multiplies_commander_damage_not_life_loss():
    engine = _engine()
    enchantment = GameObject(_db().get_card("Triple Threat"), owner_id="p2", zone=Zone.BATTLEFIELD)
    enchantment.controller_id = "p2"
    bind_from_catalogue(enchantment)
    engine.state.add_to_battlefield(enchantment)
    commander = GameObject(_db().get_card("Isamaru, Hound of Konda"), owner_id="p1", zone=Zone.BATTLEFIELD)
    commander.controller_id = "p1"
    commander.is_commander = True
    engine.state.add_to_battlefield(commander)
    victim = engine.state.player_by_id("p2")
    engine.rules.deal_damage(victim, 2, source=commander, combat=True)
    assert victim.life == 38
    assert victim.commander_damage[commander.instance_id]["amount"] == 6


def test_mishra_attack_meld_spec_preserves_tapped_attacking_result():
    result = parse_oracle(_db().get_card("Mishra, Claimed by Gix"))
    assert result.modeled
    meld = result.specs[0].effects[-1]
    assert meld.type == "meld"
    assert meld.params["partner_name"] == "phyrexian dragon engine"
    assert meld.params["tapped_attacking"] is True
