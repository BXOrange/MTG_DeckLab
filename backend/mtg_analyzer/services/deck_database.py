"""SQLite-backed persistence for saved decklists, keyed by UUID.

Reference: docs/04_SERVER_CLIENT_ARCHITECTURE.md (PART 4, REST
endpoints), backend/ToDo_Backend.md "Deck persistence".

Unlike `mtg_analyzer.services.card_database.CACHE_ROOT` (Scryfall data,
entirely disposable — see docs/08_CARD_CACHE_EXPORT_IMPORT.md), saved
decks are real user data with no upstream source to re-fetch from. They
live under `DATA_ROOT` instead, a sibling directory that is NOT safe to
delete: there is nothing to regenerate it from.

Follows the same "one JSON blob per row" pattern as `CardDatabase` (see
its module docstring for the rationale), with `id`/`name`/`created_at`
pulled out as real columns for lookup/ordering.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Optional, Union

from mtg_analyzer.models.deck import Deck

#: Root of on-disk, persistent application data — real user data, not a
#: disposable cache. Gitignored (see repo-root .gitignore,
#: "backend/data/") for the same reason .env files are: it's local
#: state, not something to commit — but unlike backend/cache/, back
#: this up if you care about the decks in it.
DATA_ROOT = Path(__file__).resolve().parent.parent.parent / "data"

#: Default on-disk location for saved decks.
DEFAULT_DECKS_DB_PATH = DATA_ROOT / "decks.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS decks (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_decks_created_at ON decks (created_at);
"""


class DeckDatabase:
    """Local persistence for saved `Deck` objects."""

    def __init__(self, db_path: Union[str, Path] = ":memory:") -> None:
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        # See CardDatabase for why check_same_thread=False + a lock:
        # FastAPI's sync route handlers run in a thread pool, and this
        # instance is shared (api/dependencies.py) across requests.
        self._connection = sqlite3.connect(str(db_path), check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            self._connection.executescript(_SCHEMA)
            self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "DeckDatabase":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def get_deck(self, deck_id: str) -> Optional[Deck]:
        with self._lock:
            row = self._connection.execute(
                "SELECT data FROM decks WHERE id = ?", (deck_id,)
            ).fetchone()
        return Deck.from_dict(json.loads(row[0])) if row else None

    def list_decks(self) -> list[Deck]:
        """Every saved deck, newest first."""
        with self._lock:
            rows = self._connection.execute(
                "SELECT data FROM decks ORDER BY created_at DESC"
            ).fetchall()
        return [Deck.from_dict(json.loads(row[0])) for row in rows]

    def save_deck(self, deck: Deck) -> None:
        """Insert or update a deck, keyed by its id. Names need not be unique."""
        with self._lock:
            self._connection.execute(
                "INSERT INTO decks (id, name, created_at, data) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET name = excluded.name, data = excluded.data",
                (deck.id, deck.name, deck.created_at, json.dumps(deck.to_dict())),
            )
            self._connection.commit()

    def delete_deck(self, deck_id: str) -> bool:
        """Delete a saved deck. Returns whether a deck was actually removed."""
        with self._lock:
            cursor = self._connection.execute("DELETE FROM decks WHERE id = ?", (deck_id,))
            self._connection.commit()
        return cursor.rowcount > 0
