"""Persistent raw-Scryfall card store — the durable "loading" ledger.

Reference: the plan "Model all Edge Cases, the whole card database, and all
~30k MTG cards" (Phase 0a), and the user requirement for "a separate
engineering database for loading to avoid duplicate work in the future".

Why a *third* database, separate from both the app card cache and the coverage
ledger:

* The app card cache (`cache/db/cards.db`, `services/card_database.py`) stores
  `Card.to_dict()` blobs and is **wiped** by `schema_version.reconcile_schema`
  whenever the `Card` model (or the cache table) changes shape. If the one-shot
  30k bulk load lived only there, an unrelated `Card`-model tweak would throw it
  all away and force a full re-download from Scryfall — exactly the duplicate
  work we want to avoid.
* This store instead keeps the **raw Scryfall JSON** for each card, keyed by
  Oracle id. That representation is independent of our `Card` model, so it is
  *never* invalidated by a model change. Re-seeding a fresh app cache from it is
  a fast, purely local pass through `scryfall_client.card_from_scryfall_data`
  (no network, no rate limit) — see `scripts/import_bulk.py --reseed-only`.

Persistent: lives under `DATA_DIR` (not the disposable `CACHE_DIR`) and carries
no `reconcile_schema` hook of its own.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Union

from mtg_analyzer.config import DATA_DIR

#: Default on-disk location for the persistent raw-card store.
DEFAULT_RAW_STORE_PATH = DATA_DIR / "scryfall_raw.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_cards (
    oracle_id  TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    layout     TEXT NOT NULL DEFAULT '',
    json       TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_raw_cards_name ON raw_cards (name COLLATE NOCASE);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class RawCardStore:
    """Persistent store of raw Scryfall card objects, keyed by Oracle id."""

    def __init__(self, db_path: Union[str, Path] = DEFAULT_RAW_STORE_PATH) -> None:
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(str(db_path), check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            self._connection.executescript(_SCHEMA)
            self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "RawCardStore":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def upsert_many(self, raw_cards: list[dict]) -> int:
        """Insert/replace many raw Scryfall objects. Returns the count stored.

        Rows lacking an `oracle_id` (rare non-card objects) fall back to the
        Scryfall printing `id` so nothing is silently dropped.
        """
        now = _now()
        rows = []
        for data in raw_cards:
            key = data.get("oracle_id") or data.get("id")
            if not key:
                continue
            rows.append((key, data.get("name", ""), data.get("layout", ""),
                         json.dumps(data), now))
        with self._lock:
            self._connection.executemany(
                "INSERT OR REPLACE INTO raw_cards (oracle_id, name, layout, json, fetched_at) "
                "VALUES (?, ?, ?, ?, ?)",
                rows,
            )
            self._connection.commit()
        return len(rows)

    def count(self) -> int:
        with self._lock:
            return self._connection.execute("SELECT COUNT(*) FROM raw_cards").fetchone()[0]

    def iter_raw(self) -> Iterator[dict]:
        """Yield every stored raw Scryfall object (streamed, name-ordered)."""
        with self._lock:
            cursor = self._connection.execute(
                "SELECT json FROM raw_cards ORDER BY name"
            )
            rows = cursor.fetchall()
        for (blob,) in rows:
            yield json.loads(blob)
