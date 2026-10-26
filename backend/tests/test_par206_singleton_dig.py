"""One-of-two library picks reuse the existing mandatory selection continuation."""
import pytest

from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from tests.test_par144_dig_family import _answer, _card, _cast, _engine, _names, _stock


BODY = ("Look at the top two cards of your library. Put one of them into your hand "
        "and the other on the bottom of your library.")


@pytest.mark.parametrize("selection", [
    "put 1 of them into your hand and the other on the bottom of your library",
    "put 1 of those cards into your hand and the other on the bottom of your library",
    "put 1 of them into your hand. put the other on the bottom of your library",
])
def test_singleton_remainder_uses_existing_selection(selection):
    [spec] = match_clause(f"look at the top 2 cards of your library. {selection}")
    assert spec.type == "look_top_select"
    assert spec.params == {"count": 2, "select_count": 1, "select_optional": False,
                           "rest_destination": "library_bottom", "rest_order": "any"}


@pytest.mark.parametrize("name,text,kind", [
    ("A Little Chat", "Casualty 1\n" + BODY, "Instant"),
    ("Sleight of Hand", BODY, "Sorcery"),
    ("Sea Gate Oracle", "When this creature enters, " + BODY[0].lower() + BODY[1:], "Creature — Human Wizard"),
    ("Sight Beyond Sight", BODY + "\nRebound", "Sorcery"),
])
def test_real_card_is_fully_modeled(name, text, kind):
    assert parse_oracle(_card(name, kind, oracle_text=text)).modeled


@pytest.mark.parametrize("topdown,take,remaining", [
    ([], None, []),
    (["A"], "A", []),
    (["A", "B"], "A", ["B"]),
    (["A", "B"], "B", ["A"]),
    (["A", "B", "C", "D"], "A", ["C", "D", "B"]),
    (["A", "B", "C", "D"], "B", ["C", "D", "A"]),
])
def test_look_choose_one_and_bottom_other_with_short_libraries(topdown, take, remaining):
    engine, player = _engine()
    _stock(player, *[_card(name) for name in topdown])
    _cast(engine, player, BODY)
    if take is not None:
        choice = engine.state.pending_choice
        assert choice["kind"] == "look_top_select"
        assert {o["label"] for o in choice["options"]} == set(topdown[:2])
        assert all(o["id"] != "decline" for o in choice["options"])
        assert _answer(engine, {take}) == 1
    assert engine.state.pending_choice is None
    assert _names(player.hand) == ([take] if take else [])
    assert _names(list(reversed(player.library))) == remaining
    assert not player.has_lost  # Moving cards from an empty library is not drawing.


def test_following_instruction_waits_for_selection():
    engine, player = _engine()
    _stock(player, *[_card(name) for name in ["A", "B", "C", "D"]])
    _cast(engine, player, BODY + " Draw a card.")
    assert player.hand == []
    assert _answer(engine, {"B"}) == 1
    assert _names(player.hand) == ["B", "C"]
    assert _names(list(reversed(player.library))) == ["D", "A"]


def test_singleton_graveyard_remainder_uses_existing_inspection_effect():
    [spec] = match_clause("look at the top 2 cards of your library. put 1 of them into your hand "
                          "and the other into your graveyard")
    assert spec.type == "inspect_top_choose"
    assert spec.params["rest_destination"] == "graveyard"
    engine, player = _engine()
    _stock(player, *[_card(name) for name in ["A", "B", "C"]])
    _cast(engine, player, BODY.replace("on the bottom of your library", "into your graveyard"))
    assert _answer(engine, {"B"}) == 1
    assert _names(player.hand) == ["B"]
    assert "A" in _names(player.graveyard)
    assert _names(list(reversed(player.library))) == ["C"]


@pytest.mark.parametrize("text", [
    "look at the top 3 cards of your library. put 1 of them into your hand and the other on the bottom of your library",
    "look at the top x cards of your library. put 1 of them into your hand and the other on the bottom of your library",
    "look at the top 2 cards of your library. you may put 1 of them into your hand and the other on the bottom of your library",
    "look at the top 2 cards of your library. put 2 of them into your hand and the other on the bottom of your library",
    "look at the top 2 cards of your library. put 1 of them into your hand and the other into your command zone",
    "look at the top 2 cards of your library. put 1 of them into your hand and the other on the bottom of your library. the other player wins the game",
])
def test_singular_other_does_not_claim_larger_or_optional_piles(text):
    assert match_clause(text) is None
