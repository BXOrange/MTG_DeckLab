"""Tests for the structured mana cost model.

Reference: backend/ToDo_Backend.md "Mana cost model",
mtg_analyzer/models/mana_cost.py.
"""

from mtg_analyzer.models.mana_cost import (
    COLOR,
    GENERIC,
    HYBRID,
    MONO_HYBRID,
    PHYREXIAN,
    VARIABLE,
    ManaCost,
)


def test_parse_plain_cost():
    cost = ManaCost.parse("{2}{W}{U}")
    kinds = [s.kind for s in cost.symbols]
    assert kinds == [GENERIC, COLOR, COLOR]
    assert cost.symbols[0].amount == 2
    assert cost.converted_mana_cost == 4
    assert cost.color_identity == {"W", "U"}


def test_empty_cost_is_free():
    cost = ManaCost.parse("")
    assert cost.is_free
    assert cost.converted_mana_cost == 0
    assert cost.color_identity == set()


def test_hybrid_symbol_preserves_both_colors():
    cost = ManaCost.parse("{W/U}")
    (symbol,) = cost.symbols
    assert symbol.kind == HYBRID
    # cmc of a hybrid pip is 1, and it contributes both colors to identity.
    assert symbol.cmc == 1
    assert cost.color_identity == {"W", "U"}
    assert symbol.payment_options() == [("W", 0, 0), ("U", 0, 0)]


def test_monocolored_hybrid():
    cost = ManaCost.parse("{2/W}")
    (symbol,) = cost.symbols
    assert symbol.kind == MONO_HYBRID
    assert symbol.amount == 2
    assert symbol.cmc == 2  # {2/W} counts as 2 toward mana value
    # Either 1 W, or 2 generic.
    assert symbol.payment_options() == [("W", 0, 0), (None, 2, 0)]


def test_phyrexian_symbol():
    cost = ManaCost.parse("{B/P}")
    (symbol,) = cost.symbols
    assert symbol.kind == PHYREXIAN
    assert symbol.cmc == 1
    assert cost.color_identity == {"B"}
    # Pay 1 B, or 2 life.
    assert symbol.payment_options() == [("B", 0, 0), (None, 0, 2)]


def test_variable_x_counts_as_zero():
    cost = ManaCost.parse("{X}{R}")
    assert cost.symbols[0].kind == VARIABLE
    assert cost.converted_mana_cost == 1  # X is 0 until chosen


def test_colorless_symbol_is_distinct_from_generic():
    cost = ManaCost.parse("{C}")
    (symbol,) = cost.symbols
    assert symbol.kind != GENERIC
    assert symbol.payment_options() == [("C", 0, 0)]


def test_unknown_symbol_falls_back_to_generic_pip():
    # Snow {S} is not modeled; it must still count for mana value.
    cost = ManaCost.parse("{S}{R}")
    assert cost.converted_mana_cost == 2


def test_equality_by_symbols():
    assert ManaCost.parse("{1}{G}") == ManaCost.parse("{1}{G}")
    assert ManaCost.parse("{1}{G}") != ManaCost.parse("{2}{G}")
