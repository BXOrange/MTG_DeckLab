"""Tests for schema-hash drift detection across the SQLite databases.

Reference: mtg_analyzer/services/schema_version.py, backend/Done_Backend.md
"Data model / cache schema versioning".
"""

import sqlite3

import pytest

from mtg_analyzer.models.card import Card
from mtg_analyzer.models.deck import Deck
from mtg_analyzer.services.card_database import CardDatabase
from mtg_analyzer.services.deck_database import DeckDatabase
from mtg_analyzer.services.schema_version import (
    compute_schema_hash,
    read_schema_hash,
    reconcile_schema,
)


def _card(name="Sol Ring"):
    return Card(id=name, name=name, type_line="Artifact", converted_mana_cost=1)


def _stamp_stale_hash(db_path):
    """Overwrite the stored schema hash to simulate older code on disk."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("UPDATE schema_meta SET value = 'stale-hash' WHERE key = 'schema_hash'")
    conn.commit()
    conn.close()


class TestComputeHash:
    def test_hash_is_stable_and_order_independent(self, tmp_path):
        a = tmp_path / "a.py"
        b = tmp_path / "b.py"
        a.write_text("print('a')")
        b.write_text("print('b')")
        assert compute_schema_hash([a, b]) == compute_schema_hash([b, a])

    def test_hash_changes_when_a_file_changes(self, tmp_path):
        a = tmp_path / "a.py"
        a.write_text("x = 1")
        before = compute_schema_hash([a])
        a.write_text("x = 2")
        assert compute_schema_hash([a]) != before


class TestReconcile:
    def test_first_stamp_reports_change_and_stores_hash(self, tmp_path):
        src = tmp_path / "m.py"
        src.write_text("v = 1")
        conn = sqlite3.connect(":memory:")
        assert reconcile_schema(conn, [src]) is True
        assert read_schema_hash(conn) == compute_schema_hash([src])
        # Unchanged on the next open.
        assert reconcile_schema(conn, [src]) is False

    def test_on_mismatch_called_before_new_hash_written(self, tmp_path):
        src = tmp_path / "m.py"
        src.write_text("v = 1")
        conn = sqlite3.connect(":memory:")
        reconcile_schema(conn, [src])  # first stamp
        src.write_text("v = 2")  # simulate a code change

        seen = {}

        def on_mismatch(c, old, new):
            seen["old"] = old
            seen["new"] = new

        assert reconcile_schema(conn, [src], on_mismatch=on_mismatch) is True
        assert seen["old"] is not None and seen["new"] == read_schema_hash(conn)


class TestCardCacheDrift:
    def test_cache_cleared_when_stored_hash_differs(self, tmp_path):
        path = tmp_path / "cards.db"
        db = CardDatabase(path)
        db.save_card(_card())
        db.close()

        _stamp_stale_hash(path)

        reopened = CardDatabase(path)
        assert reopened.schema_reset is True
        assert reopened.get_card("Sol Ring") is None  # disposable → cleared
        reopened.close()

    def test_cache_preserved_when_hash_matches(self, tmp_path):
        path = tmp_path / "cards.db"
        db = CardDatabase(path)
        db.save_card(_card())
        db.close()

        reopened = CardDatabase(path)
        assert reopened.schema_reset is False
        assert reopened.get_card("Sol Ring") is not None
        reopened.close()


class TestDeckStoreDrift:
    def test_decks_preserved_when_stored_hash_differs(self, tmp_path):
        path = tmp_path / "decks.db"
        db = DeckDatabase(path)
        deck = Deck(name="Keep me", mainboard_text="1 Sol Ring\n")
        db.save_deck(deck)
        db.close()

        _stamp_stale_hash(path)

        reopened = DeckDatabase(path)
        assert reopened.schema_changed is True
        # Irreplaceable user data must survive a format change.
        assert reopened.get_deck(deck.id) is not None
        reopened.close()
