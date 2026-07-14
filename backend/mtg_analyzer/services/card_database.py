"""SQLite-backed local cache of Card data, keyed by Scryfall id, name, and
flavor name.

Reference: docs/concepts/06_CARD_GRAPHICS_AND_LAZY_LOADING.md (PART 3),
docs/implementation-state/IMPLEMENTATION_GUIDE.md (Week 2, Day 4-5, "CardDatabase").

Rather than one hand-maintained SQLite column per `Card` attribute, each
row stores the card's `to_dict()` output as a JSON blob alongside
indexed `id`/`name`/`flavor_name` columns for lookup. This keeps the
schema in sync with `Card` for free as fields are added, at the cost of
not being able to filter on individual card attributes in SQL
(`search_cards` matches on name only, which is all that's needed today).
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
from pathlib import Path
from typing import Optional, Union

from mtg_analyzer.config import CACHE_DIR, DB_PATH
from mtg_analyzer.models.card import Card
from mtg_analyzer.services.schema_version import reconcile_schema

_log = logging.getLogger(__name__)

#: Face separator in a multi-faced card name — see lazy_card_loader.py.
#: Tolerates single/double slash and spacing so cache lookups by a
#: slash-variant front name still match the stored full name.
_FACE_SEPARATOR_RE = re.compile(r"\s*/+\s*")

#: Root of the on-disk, lazily-populated card cache (this DB plus, in
#: mtg_analyzer/services/image_cache.py, downloaded card images). Entirely
#: disposable: deleting it just means the next lookup re-fetches from
#: Scryfall. Gitignored via the repo-root .gitignore ("backend/cache/") —
#: never commit it. Export/import instructions:
#: docs/Reference/08_CARD_CACHE_EXPORT_IMPORT.md. Overridable via the
#: MTG_CACHE_DIR env var — see mtg_analyzer/config.py.
CACHE_ROOT = CACHE_DIR

#: Default on-disk location for the lazily-populated card database.
DEFAULT_DB_PATH = DB_PATH

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cards (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    flavor_name TEXT NOT NULL DEFAULT '',
    data TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_cards_name ON cards (name COLLATE NOCASE);
-- Not unique: most rows have a blank flavor_name (only Secret Lair
-- "Godzilla"/Universes Beyond promos carry one, see Card.flavor_name).
CREATE INDEX IF NOT EXISTS idx_cards_flavor_name ON cards (flavor_name COLLATE NOCASE);
"""

#: Source files that define the *stored format* of a cached card row: the
#: serialized model (`Card.to_dict`/`from_dict`) and this table's own
#: storage. A change to either can make existing rows incompatible, so it
#: invalidates the cache (see services/schema_version.py). Deliberately
#: NOT including `scryfall_client.py`: how Scryfall data is *parsed* into a
#: Card affects stored *values* (a freshness concern), not the blob format,
#: and it changes often for unrelated reasons — hashing it would wipe the
#: cache needlessly. Refresh stale values by clearing `backend/cache/`
#: (docs/08) if a parsing fix needs to reach already-cached cards.
_SCHEMA_SOURCE_FILES = [
    Path(__file__),  # this file: table schema + how the blob is stored
    Path(__file__).resolve().parent.parent / "models" / "card.py",
]


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
            self._migrate_missing_columns()
            self._connection.executescript(_SCHEMA)
            self._connection.commit()
        #: Whether opening this DB cleared the cache due to a schema change.
        self.schema_reset = self._reconcile_schema()

    def _migrate_missing_columns(self) -> None:
        """Widen a pre-existing `cards` table with any columns added since.

        `CREATE TABLE IF NOT EXISTS` (in `_SCHEMA`) only creates the table
        on a brand-new database — it never alters an existing one, so a
        column added later (like `flavor_name`) would otherwise make the
        `CREATE INDEX` right after this fail against an on-disk DB from
        before that column existed. `_reconcile_schema`'s wipe-on-mismatch
        handles stale *values*; this handles the table *shape* itself,
        which must be fixed first — `_reconcile_schema` doesn't even run
        until after `_SCHEMA` has already touched the new column.
        """
        columns = {
            row[1] for row in self._connection.execute("PRAGMA table_info(cards)").fetchall()
        }
        if not columns:
            return  # brand-new database — _SCHEMA's CREATE TABLE handles it
        if "flavor_name" not in columns:
            self._connection.execute("ALTER TABLE cards ADD COLUMN flavor_name TEXT NOT NULL DEFAULT ''")

    def _reconcile_schema(self) -> bool:
        with self._lock:
            return reconcile_schema(
                self._connection, _SCHEMA_SOURCE_FILES, on_mismatch=self._clear_on_schema_change
            )

    @staticmethod
    def _clear_on_schema_change(
        conn: sqlite3.Connection, old: Optional[str], new: str
    ) -> None:
        # The card cache is disposable — always re-fetchable from Scryfall
        # (docs/Reference/08_CARD_CACHE_EXPORT_IMPORT.md) — so on any format drift,
        # drop cached rows and let them re-populate lazily in the current
        # format. This is what heals e.g. stale mana-cost data.
        conn.execute("DELETE FROM cards")
        if old is not None:
            _log.info("Card cache schema changed; cleared cached cards to re-fetch.")

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "CardDatabase":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def get_card(self, name: str) -> Optional[Card]:
        """Look up a card by exact name, case-insensitive.

        Also matches a multi-faced card by its front-face name (e.g.
        "Valki, God of Lies" matches a row stored under the full
        "Valki, God of Lies // Tibalt, Cosmic Impostor") — decklists
        conventionally reference such cards by their front face only, or
        with a single-slash separator ("Halvar, God of Battle / Sword of
        the Realms"). Both the exact name and the part before the first
        slash are tried as a front-face prefix. No MTG card name contains
        a literal `%`/`_`, so the LIKE prefix match needs no escaping.

        Also matches a promo printing's `flavor_name` (e.g. "Godzilla,
        King of the Monsters" hits the row stored under its real name
        "Zilortha, Strength Incarnate") — see `Card.flavor_name`.
        """
        front = _FACE_SEPARATOR_RE.split(name, maxsplit=1)[0].strip()
        with self._lock:
            row = self._connection.execute(
                "SELECT data FROM cards WHERE name = ? COLLATE NOCASE "
                "OR name LIKE ? COLLATE NOCASE "
                "OR (flavor_name != '' AND flavor_name = ? COLLATE NOCASE)",
                (name, f"{front} // %", name),
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
        """Insert or update a card, keyed by its Scryfall id.

        Two *different* printings can resolve to the same `name` — e.g. a
        plain "Nyxbloom Ancient" alongside a Universes Beyond crossover
        printing whose flavor name ("The Cloudsea Djinn") resolves back to
        the same Oracle card via the `/cards/named` fallback
        (`LazyCardLoader.load_cards`) — which would otherwise violate the
        UNIQUE `name` index with a plain `ON CONFLICT(id)` upsert (a
        *different* id doesn't trigger that clause, so the separate name
        constraint raises `IntegrityError` instead). `OR REPLACE` deletes
        *any* pre-existing row conflicting on either the `id` primary key
        or the unique `name`/collation before inserting, so the two
        printings correctly collapse onto one cache row by name — matching
        the rest of the app's card-identity model (Card lookup is always
        by name, never by printing).
        """
        with self._lock:
            self._connection.execute(
                "INSERT OR REPLACE INTO cards (id, name, flavor_name, data) VALUES (?, ?, ?, ?)",
                (card.id, card.name, card.flavor_name, json.dumps(card.to_dict())),
            )
            self._connection.commit()
