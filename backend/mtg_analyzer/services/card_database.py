"""SQLite-backed local cache of Card data, keyed by Scryfall id and name.

Reference: docs/06_CARD_GRAPHICS_AND_LAZY_LOADING.md (PART 3),
docs/IMPLEMENTATION_GUIDE.md (Week 2, Day 4-5, "CardDatabase").

Rather than one hand-maintained SQLite column per `Card` attribute, each
row stores the card's `to_dict()` output as a JSON blob alongside
indexed `id`/`name` columns for lookup. This keeps the schema in sync
with `Card` for free as fields are added, at the cost of not being able
to filter on individual card attributes in SQL (`search_cards` matches
on name only, which is all that's needed today).
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Optional, Union

from mtg_analyzer.models.card import Card

#: Root of the on-disk, lazily-populated card cache (this DB plus, in
#: mtg_analyzer/services/image_cache.py, downloaded card images). Entirely
#: disposable: deleting it just means the next lookup re-fetches from
#: Scryfall. Gitignored via the repo-root .gitignore ("backend/cache/") —
#: never commit it. Export/import instructions:
#: docs/08_CARD_CACHE_EXPORT_IMPORT.md.
CACHE_ROOT = Path(__file__).resolve().parent.parent.parent / "cache"

#: Default on-disk location for the lazily-populated card database.
DEFAULT_DB_PATH = CACHE_ROOT / "db" / "cards.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cards (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    data TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_cards_name ON cards (name COLLATE NOCASE);
"""


class CardDatabase:
    """Local persistence for `Card` objects, lazily populated from Scryfall."""

    def __init__(self, db_path: Union[str, Path] = ":memory:") -> None:
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        # FastAPI runs sync route handlers in a thread pool, so a single
        # CardDatabase instance (see api/cards.py's process-wide singleton)
        # may be called from a different thread on each request; sqlite3
        # connections aren't safe for concurrent use across threads, hence
        # check_same_thread=False plus a lock serializing access.
        self._connection = sqlite3.connect(str(db_path), check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            self._connection.executescript(_SCHEMA)
            self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "CardDatabase":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def get_card(self, name: str) -> Optional[Card]:
        """Look up a card by exact name (case-insensitive)."""
        with self._lock:
            row = self._connection.execute(
                "SELECT data FROM cards WHERE name = ? COLLATE NOCASE", (name,)
            ).fetchone()
        return Card.from_dict(json.loads(row[0])) if row else None

    def get_card_by_id(self, scryfall_id: str) -> Optional[Card]:
        with self._lock:
            row = self._connection.execute(
                "SELECT data FROM cards WHERE id = ?", (scryfall_id,)
            ).fetchone()
        return Card.from_dict(json.loads(row[0])) if row else None

    def list_cards(self) -> list[Card]:
        """Return every cached card, ordered by name — for a "browse the cache" view."""
        with self._lock:
            rows = self._connection.execute("SELECT data FROM cards ORDER BY name").fetchall()
        return [Card.from_dict(json.loads(row[0])) for row in rows]

    def search_cards(self, query: str, limit: int = 20) -> list[Card]:
        """Substring search over card names, e.g. for a card-search UI."""
        with self._lock:
            rows = self._connection.execute(
                "SELECT data FROM cards WHERE name LIKE ? COLLATE NOCASE ORDER BY name LIMIT ?",
                (f"%{query}%", limit),
            ).fetchall()
        return [Card.from_dict(json.loads(row[0])) for row in rows]

    def save_card(self, card: Card) -> None:
        """Insert or update a card, keyed by its Scryfall id."""
        with self._lock:
            self._connection.execute(
                "INSERT INTO cards (id, name, data) VALUES (?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET name = excluded.name, data = excluded.data",
                (card.id, card.name, json.dumps(card.to_dict())),
            )
            self._connection.commit()
