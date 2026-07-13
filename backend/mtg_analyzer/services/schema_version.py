"""Detect when a database's on-disk format has drifted from the code.

Reference: docs/implementation-state/Done_Backend.md "Data model / cache schema versioning".

The SQLite databases here store JSON blobs of `to_dict()` output
(`CardDatabase`, `DeckDatabase`). When the code that produces those blobs
changes shape, old rows silently become stale — e.g. adding
`Card.mana_cost_string` left cached cards without it, so they looked like
free spells (the "Sol Ring" bug).

Rather than a hand-bumped integer version (easy to forget), we hash the
source files that define a database's persisted shape — the serialized
*model* plus the DB-access *service* — and stamp that hash into the
database. On open we compare: if the code's current hash differs from the
stored one, the format may have changed and the database reacts via an
``on_mismatch`` callback (the disposable card cache clears itself; the
irreplaceable deck store only records + warns).

Note it's the model/service files that determine the stored format, not
the HTTP ``api/*.py`` routes: a field added to `Card` changes
`models/card.py`, and the routes never touch what's on disk.
"""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Optional

_META_TABLE = "schema_meta"
_HASH_KEY = "schema_hash"
_UPDATED_KEY = "schema_updated_at"

_META_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {_META_TABLE} (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

#: Callback signature: ``(conn, old_hash, new_hash) -> None``, invoked
#: before the new hash is written so it can migrate/clear stale rows.
OnMismatch = Callable[[sqlite3.Connection, Optional[str], str], None]


def compute_schema_hash(paths: Iterable[Path]) -> str:
    """A stable SHA-256 digest over the given source files' contents.

    Any change to these files — including comments/whitespace — changes
    the digest. That's intentionally conservative: a false positive only
    costs a (disposable) cache rebuild, whereas a missed real change risks
    serving data in an outdated format. Files are hashed in name order so
    the result doesn't depend on argument order.
    """
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda p: p.name):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(Path(path).read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def read_schema_hash(conn: sqlite3.Connection) -> Optional[str]:
    """The schema hash stored in this database, or None if never stamped."""
    conn.execute(_META_SCHEMA)
    row = conn.execute(
        f"SELECT value FROM {_META_TABLE} WHERE key = ?", (_HASH_KEY,)
    ).fetchone()
    return row[0] if row else None


def write_schema_hash(conn: sqlite3.Connection, value: str) -> None:
    """Stamp ``value`` (plus an updated-at timestamp) into the database."""
    conn.execute(_META_SCHEMA)
    now = datetime.now(timezone.utc).isoformat()
    conn.executemany(
        f"INSERT INTO {_META_TABLE}(key, value) VALUES (?, ?) "
        f"ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        [(_HASH_KEY, value), (_UPDATED_KEY, now)],
    )
    conn.commit()


def reconcile_schema(
    conn: sqlite3.Connection,
    source_files: Iterable[Path],
    on_mismatch: Optional[OnMismatch] = None,
) -> bool:
    """Compare stored vs. current schema hash and stamp the current one.

    Returns whether the hash changed (True also on a never-stamped
    database). When it changed, ``on_mismatch`` is called *before* the new
    hash is written, so it can clear/migrate the old rows in the same
    transaction. Clearing an already-empty (fresh) database is a harmless
    no-op, so first-run stamping and real drift take the same path.
    """
    current = compute_schema_hash(source_files)
    stored = read_schema_hash(conn)
    if stored == current:
        return False
    if on_mismatch is not None:
        on_mismatch(conn, stored, current)
    write_schema_hash(conn, current)
    return True
