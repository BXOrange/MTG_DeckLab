"""Tests for the pure card-criteria matcher (mtg_analyzer/models/card_query.py)."""

import pytest

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.cards import card_query


def card(name, type_line, cmc=0, colors=None):
    return Card(
        id=name,
        name=name,
        type_line=type_line,
        converted_mana_cost=cmc,
        color_identity=set(colors or []),
    )


FOREST = card("Forest", "Basic Land — Forest")
WASTES = card("Wastes", "Basic Land")
COMMAND_TOWER = card("Command Tower", "Land")
BEAR = card("Grizzly Bears", "Creature — Bear", cmc=2, colors=["G"])
DRAGON = card("Shivan Dragon", "Creature — Dragon", cmc=6, colors=["R"])
SOL_RING = card("Sol Ring", "Artifact", cmc=1)


def test_empty_criteria_matches_anything():
    for c in (FOREST, BEAR, SOL_RING):
        assert card_query.matches(c, "")
        assert card_query.matches(c, None)
        assert card_query.matches(c, {})


def test_string_shorthand_is_type_substring():
    assert card_query.matches(BEAR, "Creature")
    assert card_query.matches(FOREST, "Land")
    assert not card_query.matches(BEAR, "Land")


def test_type_substring_spans_supertype_and_subtype():
    assert card_query.matches(FOREST, "Basic Land")
    assert card_query.matches(FOREST, "Forest")
    assert not card_query.matches(COMMAND_TOWER, "Basic")


def test_type_list_is_an_or():
    farseek = {"type": ["Plains", "Island", "Swamp", "Mountain"]}
    assert not card_query.matches(FOREST, farseek)  # Forest is none of them
    assert card_query.matches(card("Tundra", "Land — Plains Island"), farseek)


def test_basic_flag():
    assert card_query.matches(FOREST, {"basic": True})
    assert card_query.matches(WASTES, {"basic": True})
    assert not card_query.matches(COMMAND_TOWER, {"basic": True})


def test_mana_value_bounds():
    assert card_query.matches(BEAR, {"type": "Creature", "max_mana_value": 3})
    assert not card_query.matches(DRAGON, {"type": "Creature", "max_mana_value": 3})
    assert card_query.matches(DRAGON, {"min_mana_value": 6})
    assert not card_query.matches(BEAR, {"min_mana_value": 6})


def test_name_is_exact_case_insensitive():
    assert card_query.matches(SOL_RING, {"name": "sol ring"})
    assert not card_query.matches(SOL_RING, {"name": "Sol"})


def test_color_matches_color_identity():
    assert card_query.matches(BEAR, {"color": "G"})
    assert card_query.matches(BEAR, {"color": ["R", "G"]})
    assert not card_query.matches(BEAR, {"color": "R"})


def test_conditions_are_anded():
    crit = {"type": "Creature", "max_mana_value": 2, "color": "G"}
    assert card_query.matches(BEAR, crit)
    assert not card_query.matches(DRAGON, crit)  # wrong cmc and color


def test_unknown_key_fails_closed():
    with pytest.raises(ValueError):
        card_query.matches(BEAR, {"typo": "Creature"})


def test_describe_reads_naturally():
    assert card_query.describe("") == "a card"
    assert card_query.describe("Creature") == "a Creature card"
    assert card_query.describe({"basic": True}) == "a basic card"
    assert "mana value ≤ 3" in card_query.describe({"type": "Creature", "max_mana_value": 3})
    assert "Artifact" in card_query.describe("Artifact")
