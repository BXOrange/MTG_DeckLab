"""PAR-30 — the pre-daybound Innistrad werewolf day/night check.

"At the beginning of each upkeep, if no spells were cast last turn, transform
~." (front → werewolf) and its mirror "…if a player cast 2 or more spells
last turn, transform ~." (back → human) — RULE 603.4 intervening-if over
`ConditionalEffect`'s `no_spells_cast_last_turn` /
`two_or_more_spells_cast_last_turn` keys, reading
`GameState._last_turn_spell_count` (the same field the daybound/nightbound
RULE 731.2 check uses).
"""

from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine


def test_front_condition_parses():
    specs = parse_effect_body("if no spells were cast last turn, transform ~")
    assert specs == [
        type(specs[0])("transform", {}, condition={"no_spells_cast_last_turn": True})
    ]


def test_back_condition_parses_digit_and_word():
    for text in (
        "if a player cast 2 or more spells last turn, transform ~",
        "if a player cast two or more spells last turn, transform ~",
    ):
        specs = parse_effect_body(text)
        assert specs is not None
        assert specs[0].condition == {"two_or_more_spells_cast_last_turn": True}


def test_fail_closed_on_unmodelable_body():
    assert parse_effect_body(
        "if no spells were cast last turn, glorble the frobnicator"
    ) is None


def test_real_werewolf_dfc_modeled():
    c = CardDatabase(DEFAULT_DB_PATH).get_card("Reckless Waif")
    assert parse_oracle(c).modeled is True


def _engine():
    return GameEngine.new_game(
        [("p1", "A", []), ("p2", "B", [])], starting_life=20, starting_hand=0
    )


def test_execute_transforms_on_a_quiet_turn():
    db = CardDatabase(DEFAULT_DB_PATH)
    eng = _engine()
    o = GameObject(db.get_card("Reckless Waif"), owner_id="p1", zone=Zone.BATTLEFIELD)
    o.controller_id = "p1"
    eng.state.add_to_battlefield(o)
    bind_from_catalogue(o)
    assert o.transformed is False

    for _ in range(14):  # roll through to the next upkeep or two, no spells cast
        eng.advance_step()
        eng.resolve_until_stable()

    assert o.transformed is True


def test_execute_does_not_transform_turn_one():
    db = CardDatabase(DEFAULT_DB_PATH)
    eng = _engine()
    o = GameObject(db.get_card("Reckless Waif"), owner_id="p1", zone=Zone.BATTLEFIELD)
    o.controller_id = "p1"
    eng.state.add_to_battlefield(o)
    bind_from_catalogue(o)
    # First upkeep of the game — no "last turn" to evaluate.
    eng.resolve_until_stable()
    assert eng.state._last_turn_player_id is None
    assert o.transformed is False
