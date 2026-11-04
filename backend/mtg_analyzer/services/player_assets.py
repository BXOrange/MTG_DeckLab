"""SQLite-backed storage for a player's custom art uploads and preferences.

Three things a player sets in Profil (frontend profileView.js) live here:

* **Token images** - art for a token that has no real Scryfall art
  (a synthesized "create a 1/1 white Soldier" token, see
  `services/token_database.synthesize_token_card`), keyed by token name.
* **Sleeves** - a generic card-back design, keyed by a generated id and
  given a label; selectable per saved deck (`Deck.sleeve_id`,
  `services/deck_database.py`) and used as the game board's fallback
  "back of card" art (`frontend/src/js/gameBoardView.js` `resolveImageUrl`)
  for a face-down/transformed object with no real art of its own.
* **Favorite decks** - a set of `Deck.id`s a player has starred (Profil tab).

PLR-16: every row is owned by an account's `player_uuid` (plan section 1: assets
reference the UUID, never the name, so a rename cannot change ownership). The API
(`api/player_assets.py`) takes the owner from the verified session, never from a URL
or form field, and nothing here is readable by another account: the board only ever
shows the *local* player's own sleeve/token art, so there is no cross-seat read.

Rows written before accounts existed are keyed by the old free-text profile name and
sit in the same tables with `owner_uuid IS NULL` + `legacy_name` set. Every query
below filters on `owner_uuid = ?`, so those rows are invisible to the runtime until
`scripts/migrate_legacy_decks.py` assigns them (SQL: a NULL owner never matches).

Image bytes are stored directly as a BLOB column (unlike
`services/image_cache.py`, which caches Scryfall art on disk) - these
are small user uploads with no upstream to re-fetch, and keeping them
out of the filesystem means a `token_name`/`sleeve_id` never has to be
sanitized into a safe filename.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional, Union

from mtg_analyzer.config import (
    DATA_DIR,
    PLAYER_ASSET_MAX_COUNT,
    PLAYER_ASSET_MAX_TOTAL_BYTES,
    PLAYER_ASSET_STORE_MAX_BYTES,
    PLAYER_ASSETS_DB_PATH,
)

#: Real user data with no upstream source — lives beside decks.db, not
#: the disposable Scryfall cache (see services/deck_database.py DATA_ROOT).
#: Overridable via the MTG_DATA_DIR env var — see mtg_analyzer/config.py.
DATA_ROOT = DATA_DIR

DEFAULT_PLAYER_ASSETS_DB_PATH = PLAYER_ASSETS_DB_PATH

#: Asset kinds and their per-owner key column (table -> key column).
ASSET_TABLES = {"token_images": "token_name", "sleeves": "sleeve_id", "favorite_decks": "deck_id"}

#: Extra columns per table beyond (id, owner_uuid, legacy_name, key, updated_at).
_EXTRA_COLUMNS = {
    "token_images": "content_type TEXT NOT NULL, data BLOB NOT NULL",
    "sleeves": "label TEXT NOT NULL, content_type TEXT NOT NULL, data BLOB NOT NULL",
    "favorite_decks": "",
}

#: Columns carried over from a pre-PLR-16 table (its `player_name` becomes `legacy_name`).
_LEGACY_COPY_COLUMNS = {
    "token_images": "token_name, content_type, data, updated_at",
    "sleeves": "sleeve_id, label, content_type, data, updated_at",
    "favorite_decks": "deck_id, updated_at",
}


def _table_ddl(table: str) -> list[str]:
    """DDL of the current (version 1) shape of one asset table.

    Invariant in SQL: a row is owned (`owner_uuid`) or legacy (`legacy_name`), never neither;
    one row per (owner, key); legacy rows keep the old (name, key) uniqueness.
    """
    key = ASSET_TABLES[table]
    extra = _EXTRA_COLUMNS[table]
    extra_sql = f"{extra}, " if extra else ""
    return [
        f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, owner_uuid TEXT, legacy_name TEXT, "
        f"{key} TEXT NOT NULL, {extra_sql}updated_at TEXT NOT NULL, "
        f"CHECK (owner_uuid IS NOT NULL OR legacy_name IS NOT NULL))",
        f"CREATE UNIQUE INDEX ux_{table}_owner ON {table} (owner_uuid, {key}) WHERE owner_uuid IS NOT NULL",
        f"CREATE UNIQUE INDEX ux_{table}_legacy ON {table} (legacy_name, {key}) WHERE legacy_name IS NOT NULL",
    ]


#: PRAGMA user_version after the owner-column migration.
SCHEMA_VERSION = 1


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}


def migrate_schema(connection: sqlite3.Connection) -> None:
    """Bring a store to `SCHEMA_VERSION` in one transaction (versioned, additive for the data).

    A pre-PLR-16 store (tables keyed by `player_name`) is rebuilt in place: every row is kept
    byte-for-byte, its name moves to `legacy_name` and `owner_uuid` stays NULL (unassigned,
    invisible to the runtime). A new store gets the final shape directly.
    """
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    if version >= SCHEMA_VERSION:
        return
    connection.execute("BEGIN")
    try:
        for table in ASSET_TABLES:
            legacy = bool(_columns(connection, table)) and "player_name" in _columns(connection, table)
            if legacy:
                connection.execute(f"ALTER TABLE {table} RENAME TO {table}_old")
            for statement in _table_ddl(table):
                connection.execute(statement)
            if legacy:
                cols = _LEGACY_COPY_COLUMNS[table]
                connection.execute(
                    f"INSERT INTO {table} (legacy_name, {cols}) SELECT player_name, {cols} FROM {table}_old"
                )
                connection.execute(f"DROP TABLE {table}_old")
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        connection.execute("COMMIT")
    except Exception:
        connection.execute("ROLLBACK")
        raise


class AssetQuotaError(Exception):
    """BUG-43: an account's token-image + sleeve uploads would exceed its quota."""


class PlayerAssetStore:
    """Per-account token-image, sleeve and favorite-deck storage (keyed by `player_uuid`)."""

    def __init__(self, db_path: Union[str, Path] = DEFAULT_PLAYER_ASSETS_DB_PATH) -> None:
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False + a lock: shared across FastAPI's thread
        # pool, same as CardDatabase/DeckDatabase (see their docstrings).
        # isolation_level=None: transactions are explicit (BEGIN in the migration).
        self._connection = sqlite3.connect(str(db_path), check_same_thread=False, isolation_level=None)
        self._lock = threading.RLock()
        with self._lock:
            migrate_schema(self._connection)

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "PlayerAssetStore":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    @property
    def schema_version(self) -> int:
        return self._connection.execute("PRAGMA user_version").fetchone()[0]

    def _check_quota(self, owner_uuid: str, table: str, key_col: str, key: str, new_bytes: int) -> None:
        """Raise `AssetQuotaError` if saving ``new_bytes`` under ``key`` busts the quota.

        Called with ``self._lock`` held. Replacing an existing row only counts
        the size difference, so re-uploading never fails an account at its limit.
        """
        count = total = 0
        replaced = 0
        for tbl in ("token_images", "sleeves"):
            row = self._connection.execute(
                f"SELECT COUNT(*), COALESCE(SUM(LENGTH(data)), 0) FROM {tbl} WHERE owner_uuid = ?",
                (owner_uuid,),
            ).fetchone()
            count += row[0]
            total += row[1]
        existing = self._connection.execute(
            f"SELECT LENGTH(data) FROM {table} WHERE owner_uuid = ? AND {key_col} = ?",
            (owner_uuid, key),
        ).fetchone()
        if existing is not None:
            replaced = existing[0]
            count -= 1
        # The whole-store cap counts legacy rows too: they occupy the same disk.
        store_total = sum(
            self._connection.execute(
                f"SELECT COALESCE(SUM(LENGTH(data)), 0) FROM {tbl}"
            ).fetchone()[0]
            for tbl in ("token_images", "sleeves")
        )
        if store_total - replaced + new_bytes > PLAYER_ASSET_STORE_MAX_BYTES:
            raise AssetQuotaError("Der Upload-Speicher ist voll - bitte zuerst Dateien löschen")
        if count + 1 > PLAYER_ASSET_MAX_COUNT or total - replaced + new_bytes > PLAYER_ASSET_MAX_TOTAL_BYTES:
            raise AssetQuotaError("Upload-Kontingent für dieses Konto erreicht - bitte zuerst Dateien löschen")

    # -- Token images ------------------------------------------------------

    def list_token_images(self, owner_uuid: str) -> list[dict[str, str]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT token_name, updated_at FROM token_images "
                "WHERE owner_uuid = ? ORDER BY token_name",
                (owner_uuid,),
            ).fetchall()
        return [{"token_name": row[0], "updated_at": row[1]} for row in rows]

    def get_token_image(self, owner_uuid: str, token_name: str) -> Optional[tuple[str, bytes]]:
        with self._lock:
            row = self._connection.execute(
                "SELECT content_type, data FROM token_images WHERE owner_uuid = ? AND token_name = ?",
                (owner_uuid, token_name),
            ).fetchone()
        return (row[0], row[1]) if row else None

    def save_token_image(self, owner_uuid: str, token_name: str, content_type: str, data: bytes) -> None:
        with self._lock:
            self._check_quota(owner_uuid, "token_images", "token_name", token_name, len(data))
            self._connection.execute(
                "INSERT INTO token_images (owner_uuid, token_name, content_type, data, updated_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(owner_uuid, token_name) WHERE owner_uuid IS NOT NULL DO UPDATE SET "
                "content_type = excluded.content_type, data = excluded.data, updated_at = excluded.updated_at",
                (owner_uuid, token_name, content_type, data, _now()),
            )

    def delete_token_image(self, owner_uuid: str, token_name: str) -> bool:
        with self._lock:
            cursor = self._connection.execute(
                "DELETE FROM token_images WHERE owner_uuid = ? AND token_name = ?",
                (owner_uuid, token_name),
            )
        return cursor.rowcount > 0

    # -- Sleeves -------------------------------------------------------------

    def list_sleeves(self, owner_uuid: str) -> list[dict[str, str]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT sleeve_id, label, updated_at FROM sleeves WHERE owner_uuid = ? ORDER BY label",
                (owner_uuid,),
            ).fetchall()
        return [{"sleeve_id": row[0], "label": row[1], "updated_at": row[2]} for row in rows]

    def get_sleeve(self, owner_uuid: str, sleeve_id: str) -> Optional[tuple[str, bytes]]:
        with self._lock:
            row = self._connection.execute(
                "SELECT content_type, data FROM sleeves WHERE owner_uuid = ? AND sleeve_id = ?",
                (owner_uuid, sleeve_id),
            ).fetchone()
        return (row[0], row[1]) if row else None

    def save_sleeve(self, owner_uuid: str, sleeve_id: str, label: str, content_type: str, data: bytes) -> None:
        with self._lock:
            self._check_quota(owner_uuid, "sleeves", "sleeve_id", sleeve_id, len(data))
            self._connection.execute(
                "INSERT INTO sleeves (owner_uuid, sleeve_id, label, content_type, data, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(owner_uuid, sleeve_id) WHERE owner_uuid IS NOT NULL DO UPDATE SET "
                "label = excluded.label, content_type = excluded.content_type, "
                "data = excluded.data, updated_at = excluded.updated_at",
                (owner_uuid, sleeve_id, label, content_type, data, _now()),
            )

    def delete_sleeve(self, owner_uuid: str, sleeve_id: str) -> bool:
        with self._lock:
            cursor = self._connection.execute(
                "DELETE FROM sleeves WHERE owner_uuid = ? AND sleeve_id = ?",
                (owner_uuid, sleeve_id),
            )
        return cursor.rowcount > 0

    # -- Favorite decks --------------------------------------------------

    def list_favorite_decks(self, owner_uuid: str) -> list[str]:
        """This account's starred `Deck.id`s, most recently starred first."""
        with self._lock:
            rows = self._connection.execute(
                "SELECT deck_id FROM favorite_decks WHERE owner_uuid = ? ORDER BY updated_at DESC",
                (owner_uuid,),
            ).fetchall()
        return [row[0] for row in rows]

    def add_favorite_deck(self, owner_uuid: str, deck_id: str) -> None:
        with self._lock:
            self._connection.execute(
                "INSERT INTO favorite_decks (owner_uuid, deck_id, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(owner_uuid, deck_id) WHERE owner_uuid IS NOT NULL "
                "DO UPDATE SET updated_at = excluded.updated_at",
                (owner_uuid, deck_id, _now()),
            )

    def remove_favorite_deck(self, owner_uuid: str, deck_id: str) -> bool:
        with self._lock:
            cursor = self._connection.execute(
                "DELETE FROM favorite_decks WHERE owner_uuid = ? AND deck_id = ?",
                (owner_uuid, deck_id),
            )
        return cursor.rowcount > 0

    # -- Account lifecycle (PLR-16) --------------------------------------------

    def count_for_owner(self, owner_uuid: str) -> dict[str, int]:
        """Row counts per asset kind (never content) - the account-deletion preview (plan section 6)."""
        with self._lock:
            return {
                table: self._connection.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE owner_uuid = ?", (owner_uuid,)
                ).fetchone()[0]
                for table in ASSET_TABLES
            }

    def delete_all_for_owner(self, owner_uuid: str) -> int:
        """Drop every row (token images, sleeves, favorites) the account owns; return the count.

        The hook behind account deletion (`bind_account_cleanup`, plan section 6: deleting
        an account removes its assets). Never matches legacy rows (NULL owner).
        """
        if not owner_uuid:
            return 0
        with self._lock:
            removed = 0
            for table in ASSET_TABLES:
                removed += self._connection.execute(
                    f"DELETE FROM {table} WHERE owner_uuid = ?", (owner_uuid,)
                ).rowcount
        return removed

    def purge_orphans(self, live_owner_uuids: Iterable[str]) -> int:
        """Delete rows owned by an account that no longer exists; legacy (NULL owner) rows stay.

        For an operator/admin job (PLR-9d/9e), never an automatic startup sweep: with a lost or
        restored `accounts.db` the live set would be wrong and wipe valid assets.
        """
        live = list(live_owner_uuids)
        marks = ",".join("?" for _ in live)
        condition = f"owner_uuid IS NOT NULL AND owner_uuid NOT IN ({marks})" if live else "owner_uuid IS NOT NULL"
        with self._lock:
            return sum(
                self._connection.execute(f"DELETE FROM {table} WHERE {condition}", live).rowcount
                for table in ASSET_TABLES
            )


def bind_account_cleanup(accounts, assets: PlayerAssetStore) -> None:
    """Make `accounts.delete_account` also remove that account's assets (PLR-16).

    `accounts` is an `AccountStore`. Disabling an account is reversible and keeps its assets.
    """
    accounts.add_delete_listener(assets.delete_all_for_owner)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
