"""Tests for the SQLite-backed CardDatabase.

Reference: docs/06_CARD_GRAPHICS_AND_LAZY_LOADING.md (PART 3).
"""

from mtg_analyzer.models.card import Card
from mtg_analyzer.services.card_database import CardDatabase


def make_card(**overrides) -> Card:
    defaults = dict(
        id="11111111-1111-1111-1111-111111111111",
        name="Lightning Bolt",
        type_line="Instant",
        mana_cost={"W": 0, "U": 0, "B": 0, "R": 1, "G": 0, "C": 0},
        converted_mana_cost=1,
        color_identity={"R"},
        is_instant=True,
        oracle_text="Lightning Bolt deals 3 damage to any target.",
    )
    defaults.update(overrides)
    return Card(**defaults)


class TestSaveAndGet:
    def test_get_card_by_exact_name(self):
        db = CardDatabase()
        db.save_card(make_card())
        card = db.get_card("Lightning Bolt")
        assert card is not None
        assert card.name == "Lightning Bolt"
        assert card.oracle_text == "Lightning Bolt deals 3 damage to any target."

    def test_get_card_is_case_insensitive(self):
        db = CardDatabase()
        db.save_card(make_card())
        assert db.get_card("lightning bolt") is not None
        assert db.get_card("LIGHTNING BOLT") is not None

    def test_get_missing_card_returns_none(self):
        db = CardDatabase()
        assert db.get_card("Nonexistent Card") is None

    def test_get_card_by_id(self):
        db = CardDatabase()
        db.save_card(make_card())
        card = db.get_card_by_id("11111111-1111-1111-1111-111111111111")
        assert card is not None
        assert card.name == "Lightning Bolt"

    def test_save_card_round_trips_all_fields(self):
        db = CardDatabase()
        original = make_card(keywords=["Flash"], set_code="lea", rarity="common")
        db.save_card(original)
        restored = db.get_card("Lightning Bolt")
        assert restored == original


class TestUpsert:
    def test_save_card_twice_updates_in_place(self):
        db = CardDatabase()
        db.save_card(make_card(oracle_text="old text"))
        db.save_card(make_card(oracle_text="new text"))
        card = db.get_card("Lightning Bolt")
        assert card.oracle_text == "new text"

    def test_save_card_renamed_updates_name_lookup(self):
        db = CardDatabase()
        db.save_card(make_card(name="Old Name"))
        db.save_card(make_card(name="New Name"))
        assert db.get_card("Old Name") is None
        assert db.get_card("New Name") is not None


class TestListCards:
    def test_lists_all_cards_ordered_by_name(self):
        db = CardDatabase()
        db.save_card(make_card(id="22222222-2222-2222-2222-222222222222", name="Counterspell"))
        db.save_card(make_card(id="11111111-1111-1111-1111-111111111111", name="Lightning Bolt"))
        assert [c.name for c in db.list_cards()] == ["Counterspell", "Lightning Bolt"]

    def test_empty_database_returns_empty_list(self):
        db = CardDatabase()
        assert db.list_cards() == []


class TestSearch:
    def test_search_matches_substring(self):
        db = CardDatabase()
        db.save_card(make_card())
        db.save_card(make_card(id="22222222-2222-2222-2222-222222222222", name="Counterspell"))
        results = db.search_cards("bolt")
        assert [c.name for c in results] == ["Lightning Bolt"]

    def test_search_respects_limit(self):
        db = CardDatabase()
        for i in range(5):
            db.save_card(make_card(id=f"card-{i}", name=f"Bolt {i}"))
        results = db.search_cards("Bolt", limit=2)
        assert len(results) == 2

    def test_search_no_match_returns_empty_list(self):
        db = CardDatabase()
        db.save_card(make_card())
        assert db.search_cards("nonexistent") == []
