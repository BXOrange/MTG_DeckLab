"""Tests for the SQLite-backed DeckDatabase.

Reference: docs/implementation-state/Done_Backend.md "Deck persistence".
"""

from mtg_analyzer.models.decks.deck import Deck
from mtg_analyzer.services.deck_database import DeckDatabase
from tests.support.auth import TEST_PLAYER_UUID


class TestSaveAndGet:
    def test_get_saved_deck_by_id(self):
        db = DeckDatabase()
        deck = Deck(name="Goblins", commander_text="1 Krenko, Mob Boss\n")
        db.save_private(deck, TEST_PLAYER_UUID)

        fetched = db.get_deck(deck.id, TEST_PLAYER_UUID)
        assert fetched == deck

    def test_get_missing_deck_returns_none(self):
        db = DeckDatabase()
        assert db.get_deck("nonexistent-id", TEST_PLAYER_UUID) is None

    def test_duplicate_names_are_allowed(self):
        db = DeckDatabase()
        a = Deck(name="Goblins")
        b = Deck(name="Goblins")
        db.save_private(a, TEST_PLAYER_UUID)
        db.save_private(b, TEST_PLAYER_UUID)

        assert db.get_deck(a.id, TEST_PLAYER_UUID).id == a.id
        assert db.get_deck(b.id, TEST_PLAYER_UUID).id == b.id
        assert {d.id for d in db.list_decks(TEST_PLAYER_UUID)} == {a.id, b.id}


class TestUpsert:
    def test_save_deck_twice_updates_in_place(self):
        db = DeckDatabase()
        deck = Deck(id="deck-1", name="Old Name")
        db.save_private(deck, TEST_PLAYER_UUID)

        deck.name = "New Name"
        db.save_private(deck, TEST_PLAYER_UUID)

        fetched = db.get_deck("deck-1", TEST_PLAYER_UUID)
        assert fetched.name == "New Name"
        assert len(db.list_decks(TEST_PLAYER_UUID)) == 1


class TestListDecks:
    def test_empty_database_returns_empty_list(self):
        db = DeckDatabase()
        assert db.list_decks(TEST_PLAYER_UUID) == []

    def test_lists_newest_first(self):
        db = DeckDatabase()
        older = Deck(id="older", name="Older", created_at="2024-01-01T00:00:00+00:00")
        newer = Deck(id="newer", name="Newer", created_at="2024-06-01T00:00:00+00:00")
        db.save_private(older, TEST_PLAYER_UUID)
        db.save_private(newer, TEST_PLAYER_UUID)

        assert [d.id for d in db.list_decks(TEST_PLAYER_UUID)] == ["newer", "older"]


class TestDeleteDeck:
    def test_delete_existing_deck_returns_true(self):
        db = DeckDatabase()
        deck = Deck(id="deck-1")
        db.save_private(deck, TEST_PLAYER_UUID)

        assert db.delete_private("deck-1", TEST_PLAYER_UUID) is True
        assert db.get_deck("deck-1", TEST_PLAYER_UUID) is None

    def test_delete_missing_deck_returns_false(self):
        db = DeckDatabase()
        assert db.delete_private("nonexistent-id", TEST_PLAYER_UUID) is False


# -- PLR-9b: scope and owner -----------------------------------------------------------------------


import sqlite3  # noqa: E402

import pytest  # noqa: E402

from mtg_analyzer.services.deck_database import DeckAccessError  # noqa: E402

ALICE, BOB = "uuid-alice", "uuid-bob"


class TestScopeAndOwner:
    def test_private_is_visible_to_its_owner_only(self):
        db = DeckDatabase()
        deck = Deck(name="Mine")
        assert db.save_private(deck, ALICE)
        assert db.get_deck(deck.id, ALICE).scope == "private"
        assert db.get_deck(deck.id, BOB) is None
        assert [d.id for d in db.list_decks(ALICE)] == [deck.id] and db.list_decks(BOB) == []
        assert db.count(ALICE) == 1 and db.count(BOB) == 0 and db.count() == 0

    def test_global_is_visible_to_every_player_and_counted_anonymously(self):
        db = DeckDatabase()
        deck = Deck(name="Shared")
        assert db.save_global(deck)
        assert db.get_deck(deck.id, ALICE).scope == "global" and db.get_deck(deck.id, BOB).owner is None
        assert db.count() == 1

    def test_a_player_identity_is_required(self):
        db = DeckDatabase()
        for bad in ("", None):
            with pytest.raises(ValueError):
                db.get_deck("x", bad)
            with pytest.raises(ValueError):
                db.save_private(Deck(), bad)

    def test_upserts_never_cross_scope_or_owner(self):
        db = DeckDatabase()
        mine, shared = Deck(name="Mine"), Deck(name="Shared")
        db.save_private(mine, ALICE)
        db.save_global(shared)
        takeover = Deck(id=mine.id, name="Bob's now")
        assert db.save_private(takeover, BOB) is False
        assert db.save_global(takeover) is False
        hijack_global = Deck(id=shared.id, name="Alice's now")
        assert db.save_private(hijack_global, ALICE) is False
        assert db.get_deck(mine.id, ALICE).name == "Mine" and db.get_deck(shared.id, ALICE).name == "Shared"
        assert db.get_deck(shared.id, ALICE).scope == "global"

    def test_delete_private_is_owner_only_and_never_removes_global(self):
        db = DeckDatabase()
        mine, shared = Deck(), Deck()
        db.save_private(mine, ALICE)
        db.save_global(shared)
        assert db.delete_private(mine.id, BOB) is False and db.delete_private(shared.id, ALICE) is False
        assert db.delete_private(mine.id, ALICE) is True
        assert db.get_deck(shared.id, ALICE) is not None

    def test_copy_makes_a_new_private_deck_and_leaves_the_source(self):
        db = DeckDatabase()
        shared = Deck(name="Shared", mainboard_text="1 Forest")
        db.save_global(shared)
        copy = db.copy_to_private(shared.id, ALICE)
        assert copy.id != shared.id and copy.scope == "private" and copy.owner == ALICE
        assert db.get_deck(copy.id, BOB) is None and db.get_deck(shared.id, BOB).scope == "global"
        assert db.copy_to_private("missing", ALICE) is None

    def test_store_derived_writes_only_derived_fields_and_skips_stale_text(self):
        db = DeckDatabase()
        shared = Deck(name="Shared", mainboard_text="1 Forest")
        db.save_global(shared)
        assert db.store_derived(shared, {"colorIdentity": ["G"]})
        assert db.get_deck(shared.id, ALICE).color_identity == ["G"]
        with pytest.raises(ValueError):
            db.store_derived(shared, {"name": "pwned"})
        stale = Deck.from_dict(shared.to_dict())
        stale.mainboard_text = "2 Forest"
        assert db.store_derived(stale, {"colorIdentity": ["R"]}) is False
        assert db.get_deck(shared.id, ALICE).color_identity == ["G"]

    @pytest.mark.parametrize("scope,owner", [
        ("private", None), ("private", ""), ("global", "uuid-alice"), ("unassigned", "uuid-alice"), ("bogus", None),
    ])
    def test_sql_rejects_invalid_scope_owner_combinations_on_insert(self, scope, owner):
        db = DeckDatabase()
        with pytest.raises(sqlite3.DatabaseError):
            db._connection.execute(
                "INSERT INTO decks (id, name, created_at, data, scope, owner) VALUES ('d', 'n', 't', '{}', ?, ?)",
                (scope, owner),
            )

    def test_sql_rejects_scope_and_owner_changes_on_existing_rows(self):
        db = DeckDatabase()
        mine, shared = Deck(), Deck()
        db.save_private(mine, ALICE)
        db.save_global(shared)
        for sql in (
            f"UPDATE decks SET owner = 'uuid-bob' WHERE id = '{mine.id}'",
            f"UPDATE decks SET scope = 'global', owner = NULL WHERE id = '{mine.id}'",
            f"UPDATE decks SET scope = 'private', owner = 'uuid-bob' WHERE id = '{shared.id}'",
            f"UPDATE decks SET scope = 'unassigned', owner = NULL WHERE id = '{shared.id}'",
            f"UPDATE decks SET owner = NULL WHERE id = '{mine.id}'",
        ):
            with pytest.raises(sqlite3.DatabaseError):
                db._connection.execute(sql)

    def test_legacy_store_gains_columns_with_rows_unassigned_and_invisible(self, tmp_path):
        path = tmp_path / "legacy.db"
        legacy = sqlite3.connect(path)
        legacy.executescript(
            "CREATE TABLE decks (id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL, data TEXT NOT NULL);"
        )
        legacy.execute("INSERT INTO decks VALUES ('old', 'Old', '2024', ?)", ('{"id": "old", "name": "Old"}',))
        legacy.commit()
        legacy.close()
        db = DeckDatabase(path)
        assert db.schema_version == 1
        assert db.get_deck("old", ALICE) is None and db.list_decks(ALICE) == [] and db.count(ALICE) == 0
        assert [d.id for d in db.operator_list_all()] == ["old"]
        assert db.operator_list_all()[0].scope == "unassigned"
        db.close()
        assert DeckDatabase(path).schema_version == 1  # reopening is a no-op

    def test_an_unassigned_row_can_only_become_global(self, tmp_path):
        db = DeckDatabase()
        db._connection.execute(
            "INSERT INTO decks (id, name, created_at, data) VALUES ('old', 'Old', 't', '{}')"
        )
        with pytest.raises(sqlite3.DatabaseError):
            db._connection.execute("UPDATE decks SET scope = 'private', owner = 'x' WHERE id = 'old'")
        db._connection.execute("UPDATE decks SET scope = 'global' WHERE id = 'old'")
