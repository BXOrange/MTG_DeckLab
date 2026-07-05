"""Tests for the SQLite-backed DeckDatabase.

Reference: backend/Done_Backend.md "Deck persistence".
"""

from mtg_analyzer.models.deck import Deck
from mtg_analyzer.services.deck_database import DeckDatabase


class TestSaveAndGet:
    def test_get_saved_deck_by_id(self):
        db = DeckDatabase()
        deck = Deck(name="Goblins", commander_text="1 Krenko, Mob Boss\n")
        db.save_deck(deck)

        fetched = db.get_deck(deck.id)
        assert fetched == deck

    def test_get_missing_deck_returns_none(self):
        db = DeckDatabase()
        assert db.get_deck("nonexistent-id") is None

    def test_duplicate_names_are_allowed(self):
        db = DeckDatabase()
        a = Deck(name="Goblins")
        b = Deck(name="Goblins")
        db.save_deck(a)
        db.save_deck(b)

        assert db.get_deck(a.id).id == a.id
        assert db.get_deck(b.id).id == b.id
        assert {d.id for d in db.list_decks()} == {a.id, b.id}


class TestUpsert:
    def test_save_deck_twice_updates_in_place(self):
        db = DeckDatabase()
        deck = Deck(id="deck-1", name="Old Name")
        db.save_deck(deck)

        deck.name = "New Name"
        db.save_deck(deck)

        fetched = db.get_deck("deck-1")
        assert fetched.name == "New Name"
        assert len(db.list_decks()) == 1


class TestListDecks:
    def test_empty_database_returns_empty_list(self):
        db = DeckDatabase()
        assert db.list_decks() == []

    def test_lists_newest_first(self):
        db = DeckDatabase()
        older = Deck(id="older", name="Older", created_at="2024-01-01T00:00:00+00:00")
        newer = Deck(id="newer", name="Newer", created_at="2024-06-01T00:00:00+00:00")
        db.save_deck(older)
        db.save_deck(newer)

        assert [d.id for d in db.list_decks()] == ["newer", "older"]


class TestDeleteDeck:
    def test_delete_existing_deck_returns_true(self):
        db = DeckDatabase()
        deck = Deck(id="deck-1")
        db.save_deck(deck)

        assert db.delete_deck("deck-1") is True
        assert db.get_deck("deck-1") is None

    def test_delete_missing_deck_returns_false(self):
        db = DeckDatabase()
        assert db.delete_deck("nonexistent-id") is False
