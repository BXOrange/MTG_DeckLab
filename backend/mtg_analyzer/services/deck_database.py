"""SQLite-backed persistence for saved decklists, keyed by UUID.

Reference: docs/concepts/04_SERVER_CLIENT_ARCHITECTURE.md (PART 4, REST
endpoints), docs/implementation-state/Done_Backend.md "Deck persistence".

Unlike `mtg_analyzer.services.card_database.CACHE_ROOT` (Scryfall data,
entirely disposable — see docs/Reference/08_CARD_CACHE_EXPORT_IMPORT.md), saved
decks are real user data with no upstream source to re-fetch from. They
live under `DATA_ROOT` instead, a sibling directory that is NOT safe to
delete: there is nothing to regenerate it from.

Follows the same "one JSON blob per row" pattern as `CardDatabase` (see
its module docstring for the rationale), with `id`/`name`/`created_at`
pulled out as real columns for lookup/ordering.

Ownership (PLR-9b, docs/concepts/15_ACCOUNT_SYSTEM_PLAN.md §4): every row has an indexed
``scope`` (``global`` / ``private`` / ``unassigned``) and ``owner`` (a ``player_uuid``)
column, and SQL triggers enforce the invariants even on upsert conflicts:

* ``private`` => owner is a non-empty player uuid;
* ``global``  => no owner (``NULL`` ownership never means global: scope says so);
* ``unassigned`` => no owner, invisible to every read below. Legacy rows land here when the
  columns are added and only ``scripts/migrate_legacy_decks.py`` moves them to ``global``;
* a private deck never changes owner or scope, a global deck never becomes private.

Every read and write takes the acting ``player_uuid`` explicitly, so a caller cannot reach a
deck without naming who is asking. ``author``, the deck name or a client token never prove
ownership; only the verified account id the API layer passes in does.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Union

from mtg_analyzer.config import DATA_DIR, DECKS_DB_PATH
from mtg_analyzer.models.decks.deck import Deck
from mtg_analyzer.services.schema_version import reconcile_schema

_log = logging.getLogger(__name__)

#: Root of on-disk, persistent application data — real user data, not a
#: disposable cache. Gitignored (see repo-root .gitignore,
#: "backend/data/") for the same reason .env files are: it's local
#: state, not something to commit — but unlike backend/cache/, back
#: this up if you care about the decks in it. Overridable via the
#: MTG_DATA_DIR env var — see mtg_analyzer/config.py.
DATA_ROOT = DATA_DIR

#: Default on-disk location for saved decks.
DEFAULT_DECKS_DB_PATH = DECKS_DB_PATH

#: Visibility classes of a stored deck (plan §4).
SCOPE_GLOBAL = "global"
SCOPE_PRIVATE = "private"
SCOPE_UNASSIGNED = "unassigned"
SCOPES = (SCOPE_GLOBAL, SCOPE_PRIVATE, SCOPE_UNASSIGNED)

#: Fields of the serialized deck that are derived caches (recomputable from the decklist text).
#: Only these may be rewritten by `store_derived`, so a cache write on a global deck can never
#: alter user-authored content.
DERIVED_FIELDS = frozenset({
    "colorIdentity", "commanders", "validationResult", "unmodeledCoverage", "unmodeledCoverageVersion",
})
_TEXT_FIELDS = ("commanderText", "mainboardText", "sideboardText")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS decks (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_decks_created_at ON decks (created_at);
"""

#: Additive, versioned migrations (``PRAGMA user_version`` = number applied). The schema-hash
#: warning below is not a migration mechanism. Each entry runs in one transaction.
_MIGRATIONS: list[str] = [
    # 1: scope + owner. Existing rows default to `unassigned` (invisible) until the operator
    # migration classifies them; the triggers hold the invariants for every later write.
    f"""
    ALTER TABLE decks ADD COLUMN scope TEXT NOT NULL DEFAULT '{SCOPE_UNASSIGNED}';
    ALTER TABLE decks ADD COLUMN owner TEXT;
    CREATE INDEX idx_decks_scope_owner ON decks (scope, owner);
    CREATE TRIGGER decks_scope_owner_insert BEFORE INSERT ON decks
    WHEN NOT (
        (NEW.scope = '{SCOPE_PRIVATE}' AND NEW.owner IS NOT NULL AND NEW.owner <> '')
        OR (NEW.scope IN ('{SCOPE_GLOBAL}', '{SCOPE_UNASSIGNED}') AND NEW.owner IS NULL)
    )
    BEGIN SELECT RAISE(ABORT, 'deck scope/owner invariant violated'); END;
    CREATE TRIGGER decks_scope_owner_update BEFORE UPDATE ON decks
    WHEN NOT (
        (NEW.scope = '{SCOPE_PRIVATE}' AND NEW.owner IS NOT NULL AND NEW.owner <> '')
        OR (NEW.scope IN ('{SCOPE_GLOBAL}', '{SCOPE_UNASSIGNED}') AND NEW.owner IS NULL)
    )
    OR (OLD.scope <> NEW.scope AND NOT (OLD.scope = '{SCOPE_UNASSIGNED}' AND NEW.scope = '{SCOPE_GLOBAL}'))
    OR (OLD.scope = '{SCOPE_PRIVATE}' AND OLD.owner IS NOT NEW.owner)
    BEGIN SELECT RAISE(ABORT, 'deck scope/owner invariant violated'); END;
    """,
]


class DeckAccessError(Exception):
    """A write that the scope/owner rules refuse (the caller maps it to 403/404)."""


#: Files defining the saved-deck storage format (the serialized model +
#: this service). Unlike the card cache, a mismatch here does NOT wipe
#: data — see `_note_schema_change`.
_SCHEMA_SOURCE_FILES = [
    Path(__file__),  # this file
    Path(__file__).resolve().parent.parent / "models" / "decks" / "deck.py",
]


class DeckDatabase:
    """Local persistence for saved `Deck` objects, scoped by owner (PLR-9b)."""

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
            self._migrate()
        #: Whether the stored schema hash differed from the code's on open.
        self.schema_changed = self._reconcile_schema()

    def _migrate(self) -> None:
        version = self._connection.execute("PRAGMA user_version").fetchone()[0]
        for index in range(version, len(_MIGRATIONS)):
            try:
                self._connection.executescript(
                    f"BEGIN;{_MIGRATIONS[index]}PRAGMA user_version = {index + 1};COMMIT;"
                )
            except Exception:
                self._connection.rollback()
                raise

    def _reconcile_schema(self) -> bool:
        with self._lock:
            return reconcile_schema(
                self._connection, _SCHEMA_SOURCE_FILES, on_mismatch=self._note_schema_change
            )

    @staticmethod
    def _note_schema_change(
        conn: sqlite3.Connection, old: Optional[str], new: str
    ) -> None:
        # Saved decks are irreplaceable user data with no upstream to
        # re-fetch — never auto-wipe them. `Deck.from_dict` tolerates
        # missing/extra fields (it uses .get defaults), so old rows still
        # load; a genuinely incompatible change would need an explicit
        # migration here. Only warn on a *real* change (old is not None),
        # not on a brand-new database's first stamp.
        if old is not None:
            _log.warning(
                "Saved-deck store format changed; keeping existing decks "
                "(no auto-migration). Verify decks still load correctly."
            )

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "DeckDatabase":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    @property
    def schema_version(self) -> int:
        with self._lock:
            return self._connection.execute("PRAGMA user_version").fetchone()[0]

    # -- visibility -----------------------------------------------------------

    @staticmethod
    def _require_player(player_uuid: str) -> str:
        # A falsy id must never silently widen or narrow a query: fail loudly instead.
        if not isinstance(player_uuid, str) or not player_uuid:
            raise ValueError("a verified player_uuid is required")
        return player_uuid

    @staticmethod
    def _deck_from_row(data: str, scope: str, owner: Optional[str]) -> Deck:
        deck = Deck.from_dict(json.loads(data))
        deck.scope, deck.owner = scope, owner
        return deck

    #: Rows `player_uuid` may read: every global deck and their own private ones.
    _VISIBLE = "(scope = 'global' OR (scope = 'private' AND owner = ?))"

    def get_deck(self, deck_id: str, player_uuid: str) -> Optional[Deck]:
        """The deck if it is global or private to ``player_uuid``, else ``None``.

        A foreign private deck and a missing id are indistinguishable here by design.
        """
        player = self._require_player(player_uuid)
        with self._lock:
            row = self._connection.execute(
                f"SELECT data, scope, owner FROM decks WHERE id = ? AND {self._VISIBLE}",
                (deck_id, player),
            ).fetchone()
        return self._deck_from_row(*row) if row else None

    def list_decks(self, player_uuid: str) -> list[Deck]:
        """Every deck ``player_uuid`` may read, newest first."""
        player = self._require_player(player_uuid)
        with self._lock:
            rows = self._connection.execute(
                f"SELECT data, scope, owner FROM decks WHERE {self._VISIBLE} ORDER BY created_at DESC",
                (player,),
            ).fetchall()
        return [self._deck_from_row(*row) for row in rows]

    def operator_list_all(self) -> list[Deck]:
        """Every stored deck of every scope, for OS-operator scripts only (never an API route).

        Running a script against the file *is* the authorization, like `manage_accounts.py`.
        """
        with self._lock:
            rows = self._connection.execute(
                "SELECT data, scope, owner FROM decks ORDER BY created_at DESC"
            ).fetchall()
        return [self._deck_from_row(*row) for row in rows]

    def count(self, player_uuid: Optional[str] = None) -> int:
        """How many decks are visible, without loading their data.

        ``None`` counts the global decks only (an anonymous overview).
        """
        with self._lock:
            if player_uuid is None:
                return self._connection.execute(
                    "SELECT COUNT(*) FROM decks WHERE scope = 'global'"
                ).fetchone()[0]
            player = self._require_player(player_uuid)
            return self._connection.execute(
                f"SELECT COUNT(*) FROM decks WHERE {self._VISIBLE}", (player,)
            ).fetchone()[0]

    # -- writes ---------------------------------------------------------------

    def save_private(self, deck: Deck, player_uuid: str) -> bool:
        """Insert or update a private deck owned by ``player_uuid``.

        Returns ``False`` when ``deck.id`` already belongs to somebody else or is global: the
        upsert's conflict branch only fires for the same private owner, so a cross-scope or
        cross-owner overwrite changes nothing (and the triggers would abort it regardless).
        """
        player = self._require_player(player_uuid)
        with self._lock:
            cursor = self._connection.execute(
                "INSERT INTO decks (id, name, created_at, data, scope, owner) "
                "VALUES (?, ?, ?, ?, 'private', ?) "
                "ON CONFLICT(id) DO UPDATE SET name = excluded.name, data = excluded.data "
                "WHERE decks.scope = 'private' AND decks.owner = excluded.owner",
                (deck.id, deck.name, deck.created_at, json.dumps(deck.to_dict()), player),
            )
            self._connection.commit()
        return cursor.rowcount > 0

    def save_global(self, deck: Deck) -> bool:
        """Internal: insert or update a global deck (admin tooling, migration, tests).

        Never reachable from a player endpoint. Refuses to touch a non-global row.
        """
        with self._lock:
            cursor = self._connection.execute(
                "INSERT INTO decks (id, name, created_at, data, scope, owner) "
                "VALUES (?, ?, ?, ?, 'global', NULL) "
                "ON CONFLICT(id) DO UPDATE SET name = excluded.name, data = excluded.data "
                "WHERE decks.scope = 'global'",
                (deck.id, deck.name, deck.created_at, json.dumps(deck.to_dict())),
            )
            self._connection.commit()
        return cursor.rowcount > 0

    def copy_to_private(self, deck_id: str, player_uuid: str) -> Optional[Deck]:
        """Copy a readable deck into a new private deck of ``player_uuid`` (new id, source untouched)."""
        source = self.get_deck(deck_id, player_uuid)
        if source is None:
            return None
        copy = Deck.from_dict(source.to_dict())
        copy.id = str(uuid.uuid4())
        copy.created_at = datetime.now(timezone.utc).isoformat()
        if not self.save_private(copy, player_uuid):  # a fresh uuid cannot collide; defensive
            raise DeckAccessError("copy refused")
        copy.scope, copy.owner = SCOPE_PRIVATE, player_uuid
        return copy

    def store_derived(self, deck: Deck, fields: dict[str, Any]) -> bool:
        """Internal: persist recomputed cache fields on a deck, whatever its scope.

        Only `DERIVED_FIELDS` can be written and only while the stored decklist text still
        equals ``deck``'s (a stale computation is dropped). Callers must already have
        authorized the read of ``deck``; this never changes content, name, scope or owner.
        """
        if not set(fields) <= DERIVED_FIELDS:
            raise ValueError(f"not derived fields: {sorted(set(fields) - DERIVED_FIELDS)}")
        with self._lock:
            row = self._connection.execute(
                "SELECT data FROM decks WHERE id = ? AND scope IN ('global', 'private')", (deck.id,)
            ).fetchone()
            if row is None:
                return False
            data = json.loads(row[0])
            current = deck.to_dict()
            if any(data.get(key) != current[key] for key in _TEXT_FIELDS):
                return False
            data.update(fields)
            self._connection.execute("UPDATE decks SET data = ? WHERE id = ?", (json.dumps(data), deck.id))
            self._connection.commit()
        return True

    def delete_private(self, deck_id: str, player_uuid: str) -> bool:
        """Delete ``player_uuid``'s own private deck. Returns whether a row was removed."""
        player = self._require_player(player_uuid)
        with self._lock:
            cursor = self._connection.execute(
                "DELETE FROM decks WHERE id = ? AND scope = 'private' AND owner = ?", (deck_id, player)
            )
            self._connection.commit()
        return cursor.rowcount > 0

    # -- administration (PLR-9d) ------------------------------------------------
    # Global decks are the admin's to manage; private decks are never readable here, only
    # counted and removed as a whole when their owner's account is deleted.

    def list_global(self) -> list[Deck]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT data, scope, owner FROM decks WHERE scope = 'global' ORDER BY created_at DESC"
            ).fetchall()
        return [self._deck_from_row(*row) for row in rows]

    def get_global(self, deck_id: str) -> Optional[Deck]:
        with self._lock:
            row = self._connection.execute(
                "SELECT data, scope, owner FROM decks WHERE id = ? AND scope = 'global'", (deck_id,)
            ).fetchone()
        return self._deck_from_row(*row) if row else None

    def delete_global(self, deck_id: str) -> bool:
        with self._lock:
            cursor = self._connection.execute("DELETE FROM decks WHERE id = ? AND scope = 'global'", (deck_id,))
            self._connection.commit()
        return cursor.rowcount > 0

    def count_private(self, player_uuid: str) -> int:
        """How many private decks ``player_uuid`` owns (a count, never content)."""
        player = self._require_player(player_uuid)
        with self._lock:
            return self._connection.execute(
                "SELECT COUNT(*) FROM decks WHERE scope = 'private' AND owner = ?", (player,)
            ).fetchone()[0]

    def delete_all_private(self, player_uuid: str) -> int:
        """Remove every private deck of a deleted account; returns how many."""
        player = self._require_player(player_uuid)
        with self._lock:
            cursor = self._connection.execute(
                "DELETE FROM decks WHERE scope = 'private' AND owner = ?", (player,)
            )
            self._connection.commit()
        return cursor.rowcount
