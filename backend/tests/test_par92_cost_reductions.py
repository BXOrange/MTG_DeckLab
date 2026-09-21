"""PAR-92 — exact parser rows for two existing cost-reduction primitives."""

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH
from tests import turn_history_events as history


def _db():
    return CardDatabase(DEFAULT_DB_PATH)


def test_second_spell_reduction_is_active_only_after_one_cast():
    card = _db().get_card("Alisaie Leveilleur")
    result = parse_oracle(card)
    assert result.modeled
    static = next(spec for spec in result.specs if spec.ability_kind == "static")
    assert static.effects[0].params == {
        "affects": "your_spells", "generic": 2,
        "active_if": {"kind": "spells_cast_this_turn", "min": 1, "max": 1},
    }


def test_basic_land_type_self_reduction_parses_all_clean_ticket_cards():
    for name in ("Draco", "Leyline Binding", "Scion of Draco"):
        result = parse_oracle(_db().get_card(name))
        cost_specs = [
            spec for spec in result.specs
            if spec.ability_kind == "static" and spec.effects
            and spec.effects[0].type == "cost_reduction"
        ]
        assert len(cost_specs) == 1
        assert cost_specs[0].effects[0].params["per"] == "basic_land_types_among_lands_you_control"


def test_second_spell_reduction_changes_the_next_spells_cost():
    engine = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_hand=0)
    source = GameObject(_db().get_card("Alisaie Leveilleur"), owner_id="p1", zone=Zone.BATTLEFIELD)
    source.controller_id = "p1"
    bind_from_catalogue(source)
    engine.state.add_to_battlefield(source)
    spell = GameObject(_db().get_card("Divination"), owner_id="p1", zone=Zone.HAND)
    spell.controller_id = "p1"
    player = engine.state.player_by_id("p1")
    player.add_to_zone(spell, Zone.HAND)
    base = engine.effective_cast_cost(player, spell).converted_mana_cost
    history.cast_spell(engine.state, "p1")
    reduced = engine.effective_cast_cost(player, spell).converted_mana_cost
    assert reduced == max(0, base - 2)
