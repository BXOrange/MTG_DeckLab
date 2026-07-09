"""Tests for parsing a permanent's mana abilities (dual lands, etc.).

Reference: mtg_analyzer/game/mana_abilities.py, docs/02 R2.6.
"""

from mtg_analyzer.models.card import Card
from mtg_analyzer.game.mana_abilities import mana_options, option_label


def land(name="Land", type_line="Land", oracle="", **kw):
    return Card(id=name, name=name, type_line=type_line, is_land=True, oracle_text=oracle, **kw)


def test_basic_land_single_option():
    assert mana_options(land("Forest", "Basic Land — Forest")) == [{"G": 1}]
    assert mana_options(land("Island", "Basic Land — Island")) == [{"U": 1}]


def test_dual_land_offers_each_color_separately():
    # The dual-land fix: one option per colour, not both at once.
    tundra = land("Tundra", "Land — Plains Island", oracle="{T}: Add {W} or {U}.")
    assert mana_options(tundra) == [{"W": 1}, {"U": 1}]


def test_tri_land_three_options():
    sanctum = land("Arcane Sanctum", oracle="{T}: Add {W}, {U}, or {B}.")
    assert mana_options(sanctum) == [{"W": 1}, {"U": 1}, {"B": 1}]


def test_multi_pip_colorless_is_one_option():
    eldrazi = land("Eldrazi Temple", oracle="{T}: Add {C}{C}.")
    assert mana_options(eldrazi) == [{"C": 2}]


def test_any_color_offers_all_five():
    tower = land("Command Tower", oracle="{T}: Add one mana of any color.")
    assert mana_options(tower) == [{"W": 1}, {"U": 1}, {"B": 1}, {"R": 1}, {"G": 1}]


def test_dual_typed_basic_land_grants_both_types():
    # A land with two basic land *types* taps for either (RULE 305.6).
    taiga = land("Taiga", "Land — Mountain Forest")
    assert mana_options(taiga) == [{"R": 1}, {"G": 1}]


def test_non_mana_permanent_has_no_options():
    bear = Card(id="b", name="Bear", type_line="Creature — Bear", is_creature=True)
    assert mana_options(bear) == []


def test_option_label_uses_glyphs():
    assert option_label({"G": 1}) == "🟢"
    assert option_label({"C": 2}) == "⟡⟡"
