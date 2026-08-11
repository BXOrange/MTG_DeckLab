"""SQLite-backed storage for a player's custom art uploads and preferences.

Three things a player sets in Profil/Einstellungen (frontend
profileView.js/connectionSettingsView.js) live here:

* **Token images** — art for a token that has no real Scryfall art
  (a synthesized "create a 1/1 white Soldier" token, see
  `services/token_database.synthesize_token_card`), keyed by token name.
* **Sleeves** — a generic card-back design, keyed by a generated id and
  given a label; selectable per saved deck (`Deck.sleeve_id`,
  `services/deck_database.py`) and used as the game board's fallback
  "back of card" art (`frontend/src/js/gameBoardView.js` `resolveImageUrl`)
  for a face-down/transformed object with no real art of its own.
* **Favorite decks** — a set of `Deck.id`s a player has starred (Profil
  tab), read by `savedDecksView.js`'s siblings (`goldfishView.js`,
  `multiplayerView.js`) to list favorites first in the deck picker.
  Deliberately per-*player-name* rather than a flag on the `Deck` itself
  (`models/deck.py`): decks aren't owned (no accounts, one shared
  `DeckDatabase`), so two players favoriting different decks out of the
  same shared list would collide on a single `Deck.is_favorite` bit.

All three are keyed by `player_name` (the free-text profile name from
Settings — this app has no auth) rather than a session or connection,
so a shared backend can serve them to *any* client asking for that
name — the mechanism that lets an opponent in a multiplayer match see
the art too.

Image bytes are stored directly as a BLOB column (unlike
`services/image_cache.py`, which caches Scryfall art on disk) — these
are small user uploads with no upstream to re-fetch, and keeping them
out of the filesystem means a `token_name`/`sleeve_id` never has to be
sanitized into a safe filename.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

from mtg_analyzer.config import DATA_DIR, PLAYER_ASSETS_DB_PATH

#: Real user data with no upstream source — lives beside decks.db, not
#: the disposable Scryfall cache (see services/deck_database.py DATA_ROOT).
#: Overridable via the MTG_DATA_DIR env var — see mtg_analyzer/config.py.
DATA_ROOT = DATA_DIR

DEFAULT_PLAYER_ASSETS_DB_PATH = PLAYER_ASSETS_DB_PATH

_SCHEMA = """
CREATE TABLE IF NOT EXISTS token_images (
    player_name TEXT NOT NULL,
    token_name TEXT NOT NULL,
    content_type TEXT NOT NULL,
    data BLOB NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (player_name, token_name)
);
CREATE TABLE IF NOT EXISTS sleeves (
    player_name TEXT NOT NULL,
    sleeve_id TEXT NOT NULL,
    label TEXT NOT NULL,
    content_type TEXT NOT NULL,
    data BLOB NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (player_name, sleeve_id)
);
CREATE TABLE IF NOT EXISTS favorite_decks (
    player_name TEXT NOT NULL,
    deck_id TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (player_name, deck_id)
);
"""


class PlayerAssetStore:
    """Per-player token-image and sleeve uploads."""

    def __init__(self, db_path: Union[str, Path] = DEFAULT_PLAYER_ASSETS_DB_PATH) -> None:
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False + a lock: shared across FastAPI's thread
        # pool, same as CardDatabase/DeckDatabase (see their docstrings).
        self._connection = sqlite3.connect(str(db_path), check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            self._connection.executescript(_SCHEMA)
            self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "PlayerAssetStore":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # -- Token images ------------------------------------------------------

    def list_token_images(self, player_name: str) -> list[dict[str, str]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT token_name, updated_at FROM token_images "
                "WHERE player_name = ? ORDER BY token_name",
                (player_name,),
            ).fetchall()
        return [{"token_name": row[0], "updated_at": row[1]} for row in rows]

    def get_token_image(self, player_name: str, token_name: str) -> Optional[tuple[str, bytes]]:
        with self._lock:
            row = self._connection.execute(
                "SELECT content_type, data FROM token_images "
                "WHERE player_name = ? AND token_name = ?",
                (player_name, token_name),
            ).fetchone()
        return (row[0], row[1]) if row else None

    def save_token_image(
        self, player_name: str, token_name: str, content_type: str, data: bytes
    ) -> None:
        with self._lock:
            self._connection.execute(
                "INSERT INTO token_images (player_name, token_name, content_type, data, updated_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(player_name, token_name) DO UPDATE SET "
                "content_type = excluded.content_type, data = excluded.data, updated_at = excluded.updated_at",
                (player_name, token_name, content_type, data, _now()),
            )
            self._connection.commit()

    def delete_token_image(self, player_name: str, token_name: str) -> bool:
        with self._lock:
            cursor = self._connection.execute(
                "DELETE FROM token_images WHERE player_name = ? AND token_name = ?",
                (player_name, token_name),
            )
            self._connection.commit()
        return cursor.rowcount > 0

    # -- Sleeves -------------------------------------------------------------

    def list_sleeves(self, player_name: str) -> list[dict[str, str]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT sleeve_id, label, updated_at FROM sleeves "
                "WHERE player_name = ? ORDER BY label",
                (player_name,),
            ).fetchall()
        return [{"sleeve_id": row[0], "label": row[1], "updated_at": row[2]} for row in rows]

    def get_sleeve(self, player_name: str, sleeve_id: str) -> Optional[tuple[str, bytes]]:
        with self._lock:
            row = self._connection.execute(
                "SELECT content_type, data FROM sleeves WHERE player_name = ? AND sleeve_id = ?",
                (player_name, sleeve_id),
            ).fetchone()
        return (row[0], row[1]) if row else None

    def save_sleeve(
        self, player_name: str, sleeve_id: str, label: str, content_type: str, data: bytes
    ) -> None:
        with self._lock:
            self._connection.execute(
                "INSERT INTO sleeves (player_name, sleeve_id, label, content_type, data, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(player_name, sleeve_id) DO UPDATE SET "
                "label = excluded.label, content_type = excluded.content_type, "
                "data = excluded.data, updated_at = excluded.updated_at",
                (player_name, sleeve_id, label, content_type, data, _now()),
            )
            self._connection.commit()

    def delete_sleeve(self, player_name: str, sleeve_id: str) -> bool:
        with self._lock:
            cursor = self._connection.execute(
                "DELETE FROM sleeves WHERE player_name = ? AND sleeve_id = ?",
                (player_name, sleeve_id),
            )
            self._connection.commit()
        return cursor.rowcount > 0

    # -- Favorite decks --------------------------------------------------

    def list_favorite_decks(self, player_name: str) -> list[str]:
        """This player's starred `Deck.id`s, most recently starred first."""
        with self._lock:
            rows = self._connection.execute(
                "SELECT deck_id FROM favorite_decks WHERE player_name = ? ORDER BY updated_at DESC",
                (player_name,),
            ).fetchall()
        return [row[0] for row in rows]

    def add_favorite_deck(self, player_name: str, deck_id: str) -> None:
        with self._lock:
            self._connection.execute(
                "INSERT INTO favorite_decks (player_name, deck_id, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(player_name, deck_id) DO UPDATE SET updated_at = excluded.updated_at",
                (player_name, deck_id, _now()),
            )
            self._connection.commit()

    def remove_favorite_deck(self, player_name: str, deck_id: str) -> bool:
        with self._lock:
            cursor = self._connection.execute(
                "DELETE FROM favorite_decks WHERE player_name = ? AND deck_id = ?",
                (player_name, deck_id),
            )
            self._connection.commit()
        return cursor.rowcount > 0

    # -- Bulk removal (PLR-4) ------------------------------------------------

    def delete_all_for_player(self, player_name: str) -> int:
        """Drop every row (token images, sleeves, favorites) under this name.

        The counterpart to a `services/lobby.py` `client_token` expiring
        (`api/multiplayer_ws.sweep_once`): once nobody is left recognized
        under this display name (`Lobby.name_in_use_by_other`), its uploads
        and preferences are abandoned data with nothing to serve them to,
        the same "player-data is deleted" half of PLR-4 as the lobby entry
        itself. Returns the total row count removed, for the caller's log.
        """
        with self._lock:
            removed = 0
            for table in ("token_images", "sleeves", "favorite_decks"):
                cursor = self._connection.execute(
                    f"DELETE FROM {table} WHERE player_name = ?", (player_name,)
                )
                removed += cursor.rowcount
            self._connection.commit()
        return removed


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
