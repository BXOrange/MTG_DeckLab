"""PAR-42 — establish day as a permanent enters."""
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle


def test_day_entry_replacement_is_parsed_and_establishes_day_once():
    card = Card(id="bv", name="Brimstone Vandal", type_line="Creature", is_creature=True,
                oracle_text="If it's neither day nor night, it becomes day as this creature enters.")
    assert parse_oracle(card).coverage != UNMODELED
    engine = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])], starting_hand=0)
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    obj.controller_id = "p1"
    bind_from_catalogue(obj)
    engine.state.add_to_battlefield(obj)
    assert engine.state.day_night == "day"
    engine.state.day_night = "night"
    engine.state.add_to_battlefield(obj)
    assert engine.state.day_night == "night"
