"""Tests for the structured mana cost model.

Reference: backend/ToDo_Backend.md "Mana cost model",
mtg_analyzer/models/mana_cost.py.
"""

from mtg_analyzer.models.card import Card
from mtg_analyzer.models.mana_cost import (
    COLOR,
    GENERIC,
    HYBRID,
    MONO_HYBRID,
    PHYREXIAN,
    VARIABLE,
    ManaCost,
)
from mtg_analyzer.models.mana_pool import ManaPool


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


class TestFromCard:
    def test_uses_raw_mana_cost_string_when_present(self):
        card = Card(
            id="x", name="Grizzly Bears", type_line="Creature — Bear",
            mana_cost_string="{1}{G}", converted_mana_cost=2,
        )
        assert ManaCost.from_card(card) == ManaCost.parse("{1}{G}")

    def test_reconstructs_generic_cost_when_raw_missing(self):
        # A stale-cache card (no mana_cost_string) like Sol Ring: {1}, no
        # colored pips, mana value 1. Must not be free (the reported bug).
        card = Card(id="x", name="Sol Ring", type_line="Artifact", converted_mana_cost=1)
        cost = ManaCost.from_card(card)
        assert cost.converted_mana_cost == 1
        assert not ManaPool().can_pay(cost)
        assert ManaPool({"C": 1}).can_pay(cost)

    def test_reconstructs_colored_cost_when_raw_missing(self):
        card = Card(
            id="x", name="Lightning Bolt", type_line="Instant",
            mana_cost={"W": 0, "U": 0, "B": 0, "R": 1, "G": 0, "C": 0},
            converted_mana_cost=1,
        )
        cost = ManaCost.from_card(card)
        assert cost.color_identity == {"R"}
        assert not ManaPool({"G": 1}).can_pay(cost)
        assert ManaPool({"R": 1}).can_pay(cost)

    def test_reconstructs_mixed_generic_and_colored(self):
        card = Card(
            id="x", name="Cultivate", type_line="Sorcery",
            mana_cost={"W": 0, "U": 0, "B": 0, "R": 0, "G": 1, "C": 0},
            converted_mana_cost=3,
        )
        cost = ManaCost.from_card(card)  # {2}{G}
        assert cost.converted_mana_cost == 3
        assert not ManaPool({"G": 1}).can_pay(cost)
        assert ManaPool({"G": 1, "C": 2}).can_pay(cost)

    def test_zero_cost_card_stays_free(self):
        card = Card(id="x", name="Ornithopter", type_line="Artifact Creature", converted_mana_cost=0)
        assert ManaCost.from_card(card).is_free
