"""Persistent local snapshot of Commander Spellbook's public combo variants.

The public export is downloaded only on first use or on an explicit refresh.
Gzip-compressed and plain JSON responses are supported. Variants and aliases
are kept in SQLite so subsequent refreshes can report added, changed, and
removed records without retaining a second full JSON copy on disk.
"""

from __future__ import annotations

from contextlib import contextmanager
import gzip
import hashlib
import json
import logging
import sqlite3
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, TextIO

import httpx2 as httpx

from mtg_analyzer.config import COMMANDER_SPELLBOOK_DB_PATH

logger = logging.getLogger(__name__)

SPELLBOOK_BULK_URL = "https://json.commanderspellbook.com/variants.json.gz"
DEFAULT_COMBO_DB_PATH = COMMANDER_SPELLBOOK_DB_PATH
_USER_AGENT = "MTG-Deck-Analyzer/0.1 (+https://github.com/BXOrange/MTG_Deck_Analyzer)"
_REQUEST_TIMEOUT_SECONDS = 120.0
_DOWNLOAD_CHUNK_BYTES = 1 << 20
_JSON_BUFFER_SIZE = 64 * 1024
_DB_BATCH_SIZE = 1000

_SCHEMA = """
CREATE TABLE IF NOT EXISTS variants (
    id TEXT PRIMARY KEY,
    data TEXT NOT NULL,
    checksum TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS variant_uses (
    variant_id TEXT NOT NULL,
    card_name TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    PRIMARY KEY (variant_id, card_name)
);
CREATE INDEX IF NOT EXISTS idx_variant_uses_card ON variant_uses (card_name);
CREATE TABLE IF NOT EXISTS aliases (
    id TEXT PRIMARY KEY,
    data TEXT NOT NULL,
    checksum TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _checksum(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _normalize_name(name: str) -> str:
    return " ".join(name.split()).casefold()


@contextmanager
def _open_snapshot_text(snapshot_path: Path) -> Iterator[TextIO]:
    with snapshot_path.open("rb") as probe:
        is_gzip = probe.read(2) == b"\x1f\x8b"

    if is_gzip:
        with gzip.open(snapshot_path, "rt", encoding="utf-8") as stream:
            yield stream
    else:
        with snapshot_path.open("rt", encoding="utf-8") as stream:
            yield stream


class _JsonStreamReader:
    """Read individual JSON values without materializing the whole export."""

    def __init__(self, stream: TextIO) -> None:
        self._stream = stream
        self._decoder = json.JSONDecoder()
        self._buffer = ""
        self._position = 0
        self._eof = False

    def _fill(self) -> None:
        chunk = self._stream.read(_JSON_BUFFER_SIZE)
        if chunk:
            self._buffer += chunk
        else:
            self._eof = True

    def _skip_whitespace(self) -> None:
        while True:
            while self._position < len(self._buffer) and self._buffer[self._position].isspace():
                self._position += 1
            if self._position < len(self._buffer) or self._eof:
                return
            self._fill()

    def peek(self) -> str:
        self._skip_whitespace()
        if self._position >= len(self._buffer):
            raise ValueError("Unexpected end of Commander Spellbook export.")
        return self._buffer[self._position]

    def consume(self, expected: str) -> None:
        actual = self.peek()
        if actual != expected:
            raise ValueError(f"Expected {expected!r} in Commander Spellbook export, got {actual!r}.")
        self._position += 1

    def read_value(self) -> Any:
        self._skip_whitespace()
        while True:
            try:
                value, end = self._decoder.raw_decode(self._buffer, self._position)
            except json.JSONDecodeError:
                if self._eof:
                    raise
                self._fill()
                continue
            self._position = end
            if self._position >= _JSON_BUFFER_SIZE:
                self._buffer = self._buffer[self._position :]
                self._position = 0
            return value


def _card_uses(variant: dict[str, Any]) -> dict[str, int]:
    uses: dict[str, int] = {}
    for use in variant.get("uses", []):
        card = use.get("card")
        name = card.get("name") if isinstance(card, dict) else None
        quantity = use.get("quantity", 1)
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"Variant {variant.get('id')!r} contains a card use without a name.")
        if not isinstance(quantity, int) or quantity < 1:
            raise ValueError(f"Variant {variant.get('id')!r} contains an invalid card quantity.")
        key = _normalize_name(name)
        uses[key] = uses.get(key, 0) + quantity
    return uses


def _stage_snapshot(snapshot_path: Path, staging_path: Path) -> tuple[dict[str, str], int, int]:
    """Stream a gzipped export into a scratch SQLite database."""
    connection = sqlite3.connect(staging_path)
    connection.executescript(
        """
        CREATE TABLE variants (id TEXT PRIMARY KEY, data TEXT NOT NULL, checksum TEXT NOT NULL);
        CREATE TABLE variant_uses (
            variant_id TEXT NOT NULL, card_name TEXT NOT NULL, quantity INTEGER NOT NULL,
            PRIMARY KEY (variant_id, card_name)
        );
        CREATE TABLE aliases (id TEXT PRIMARY KEY, data TEXT NOT NULL, checksum TEXT NOT NULL);
        """
    )
    metadata: dict[str, str] = {}
    seen_arrays: set[str] = set()
    variant_rows: list[tuple[str, str, str]] = []
    use_rows: list[tuple[str, str, int]] = []
    alias_rows: list[tuple[str, str, str]] = []
    variant_count = alias_count = 0

    def flush_variants() -> None:
        if variant_rows:
            connection.executemany("INSERT INTO variants VALUES (?, ?, ?)", variant_rows)
            connection.executemany("INSERT INTO variant_uses VALUES (?, ?, ?)", use_rows)
            variant_rows.clear()
            use_rows.clear()

    def flush_aliases() -> None:
        if alias_rows:
            connection.executemany("INSERT INTO aliases VALUES (?, ?, ?)", alias_rows)
            alias_rows.clear()

    try:
        with _open_snapshot_text(snapshot_path) as stream:
            reader = _JsonStreamReader(stream)
            reader.consume("{")
            while reader.peek() != "}":
                key = reader.read_value()
                if not isinstance(key, str):
                    raise ValueError("Commander Spellbook export has a non-string top-level key.")
                reader.consume(":")
                if key not in {"variants", "aliases"}:
                    value = reader.read_value()
                    if key in {"timestamp", "version"}:
                        metadata[key] = str(value)
                else:
                    seen_arrays.add(key)
                    reader.consume("[")
                    while reader.peek() != "]":
                        item = reader.read_value()
                        if not isinstance(item, dict):
                            raise ValueError(f"Commander Spellbook {key} entry is not an object.")
                        if key == "variants":
                            variant_id = item.get("id")
                            if not isinstance(variant_id, str) or not variant_id:
                                raise ValueError("Commander Spellbook variant is missing its id.")
                            data = _canonical_json(item)
                            variant_rows.append((variant_id, data, _checksum(item)))
                            use_rows.extend(
                                (variant_id, name, quantity)
                                for name, quantity in _card_uses(item).items()
                            )
                            variant_count += 1
                            if len(variant_rows) >= _DB_BATCH_SIZE:
                                flush_variants()
                        else:
                            alias_id = item.get("id")
                            if not isinstance(alias_id, str) or not alias_id:
                                alias_id = _checksum(item)
                            alias_rows.append((alias_id, _canonical_json(item), _checksum(item)))
                            alias_count += 1
                            if len(alias_rows) >= _DB_BATCH_SIZE:
                                flush_aliases()
                        delimiter = reader.peek()
                        if delimiter == ",":
                            reader.consume(",")
                        elif delimiter != "]":
                            raise ValueError(f"Invalid delimiter in Commander Spellbook {key} array.")
                    reader.consume("]")
                delimiter = reader.peek()
                if delimiter == ",":
                    reader.consume(",")
                elif delimiter != "}":
                    raise ValueError("Invalid delimiter in Commander Spellbook export object.")
            reader.consume("}")

        flush_variants()
        flush_aliases()
        connection.commit()
    finally:
        connection.close()

    if not {"variants", "aliases"}.issubset(seen_arrays) or variant_count == 0:
        raise ValueError("Commander Spellbook export is missing its combo arrays or contains no variants.")
    if not metadata.get("version") or not metadata.get("timestamp"):
        raise ValueError("Commander Spellbook export is missing its version or timestamp.")
    return metadata, variant_count, alias_count


class CommanderSpellbookDatabase:
    """Thread-safe, lazily initialized SQLite store of combo variants."""

    def __init__(self, db_path: str | Path = DEFAULT_COMBO_DB_PATH) -> None:
        self._path = Path(db_path) if str(db_path) != ":memory:" else None
        self._memory = self._path is None
        self._connection: sqlite3.Connection | None = None
        self._lock = threading.RLock()
        self._refresh_lock = threading.Lock()
        if self._memory:
            self._open(create=True)

    def _open(self, *, create: bool) -> sqlite3.Connection | None:
        if self._connection is not None:
            return self._connection
        if not self._memory:
            assert self._path is not None
            if not create and not self._path.exists():
                return None
            self._path.parent.mkdir(parents=True, exist_ok=True)
            db_path = self._path
        else:
            db_path = ":memory:"
        self._connection = sqlite3.connect(str(db_path), check_same_thread=False, timeout=30.0)
        self._connection.executescript(_SCHEMA)
        self._connection.commit()
        return self._connection

    def close(self) -> None:
        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None

    def _status_locked(self) -> dict[str, object]:
        connection = self._open(create=False)
        if connection is None:
            return {
                "initialized": False,
                "variantCount": 0,
                "aliasCount": 0,
                "version": None,
                "sourceTimestamp": None,
                "lastSyncedAt": None,
            }
        metadata = dict(connection.execute("SELECT key, value FROM metadata").fetchall())
        initialized = bool(metadata.get("version") and metadata.get("source_timestamp"))
        return {
            "initialized": initialized,
            "variantCount": connection.execute("SELECT COUNT(*) FROM variants").fetchone()[0],
            "aliasCount": connection.execute("SELECT COUNT(*) FROM aliases").fetchone()[0],
            "version": metadata.get("version"),
            "sourceTimestamp": metadata.get("source_timestamp"),
            "lastSyncedAt": metadata.get("last_synced_at"),
        }

    def status(self) -> dict[str, object]:
        with self._lock:
            return self._status_locked()

    def ensure_initialized(self) -> None:
        with self._refresh_lock:
            if self.status()["initialized"]:
                return
            self._refresh()

    def update(self) -> dict[str, object]:
        with self._refresh_lock:
            return self._refresh()

    def _refresh(self) -> dict[str, object]:
        with tempfile.TemporaryDirectory(prefix="spellbook-") as temp_dir:
            snapshot_path = Path(temp_dir) / "variants.json.gz"
            with httpx.Client(
                headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
                timeout=_REQUEST_TIMEOUT_SECONDS,
                follow_redirects=True,
            ) as client:
                with client.stream("GET", SPELLBOOK_BULK_URL) as response:
                    response.raise_for_status()
                    with snapshot_path.open("wb") as output:
                        for chunk in response.iter_bytes(chunk_size=_DOWNLOAD_CHUNK_BYTES):
                            output.write(chunk)
            return self._ingest_snapshot(snapshot_path, Path(temp_dir) / "staging.sqlite")

    def ingest_snapshot(self, snapshot_path: str | Path) -> dict[str, object]:
        """Ingest a local compressed snapshot; used by tests and offline maintenance."""
        with self._refresh_lock:
            return self._ingest_snapshot(Path(snapshot_path), None)

    def _ingest_snapshot(
        self, snapshot_path: Path, staging_path: Path | None
    ) -> dict[str, object]:
        with tempfile.TemporaryDirectory(prefix="spellbook-stage-") as temp_dir:
            scratch_path = staging_path or Path(temp_dir) / "staging.sqlite"
            metadata, incoming_variants, incoming_aliases = _stage_snapshot(snapshot_path, scratch_path)
            with self._lock:
                connection = self._open(create=True)
                assert connection is not None
                connection.execute("ATTACH DATABASE ? AS incoming", (str(scratch_path),))
                try:
                    connection.execute("BEGIN IMMEDIATE")
                    added = connection.execute(
                        "SELECT COUNT(*) FROM incoming.variants n "
                        "LEFT JOIN main.variants o ON o.id = n.id WHERE o.id IS NULL"
                    ).fetchone()[0]
                    changed = connection.execute(
                        "SELECT COUNT(*) FROM incoming.variants n "
                        "JOIN main.variants o ON o.id = n.id WHERE o.checksum != n.checksum"
                    ).fetchone()[0]
                    removed = connection.execute(
                        "SELECT COUNT(*) FROM main.variants o "
                        "LEFT JOIN incoming.variants n ON n.id = o.id WHERE n.id IS NULL"
                    ).fetchone()[0]
                    aliases_added = connection.execute(
                        "SELECT COUNT(*) FROM incoming.aliases n "
                        "LEFT JOIN main.aliases o ON o.id = n.id WHERE o.id IS NULL"
                    ).fetchone()[0]
                    aliases_changed = connection.execute(
                        "SELECT COUNT(*) FROM incoming.aliases n "
                        "JOIN main.aliases o ON o.id = n.id WHERE o.checksum != n.checksum"
                    ).fetchone()[0]
                    aliases_removed = connection.execute(
                        "SELECT COUNT(*) FROM main.aliases o "
                        "LEFT JOIN incoming.aliases n ON n.id = o.id WHERE n.id IS NULL"
                    ).fetchone()[0]

                    connection.execute(
                        "DELETE FROM variants WHERE id NOT IN (SELECT id FROM incoming.variants)"
                    )
                    connection.execute(
                        "INSERT INTO variants (id, data, checksum) "
                        "SELECT n.id, n.data, n.checksum FROM incoming.variants n "
                        "LEFT JOIN main.variants o ON o.id = n.id "
                        "WHERE o.id IS NULL OR o.checksum != n.checksum "
                        "ON CONFLICT(id) DO UPDATE SET data=excluded.data, checksum=excluded.checksum"
                    )
                    connection.execute("DELETE FROM variant_uses")
                    connection.execute("INSERT INTO variant_uses SELECT * FROM incoming.variant_uses")
                    connection.execute(
                        "DELETE FROM aliases WHERE id NOT IN (SELECT id FROM incoming.aliases)"
                    )
                    connection.execute(
                        "INSERT INTO aliases (id, data, checksum) "
                        "SELECT n.id, n.data, n.checksum FROM incoming.aliases n "
                        "LEFT JOIN main.aliases o ON o.id = n.id "
                        "WHERE o.id IS NULL OR o.checksum != n.checksum "
                        "ON CONFLICT(id) DO UPDATE SET data=excluded.data, checksum=excluded.checksum"
                    )
                    synced_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
                    connection.executemany(
                        "INSERT INTO metadata (key, value) VALUES (?, ?) "
                        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        [
                            ("version", metadata["version"]),
                            ("source_timestamp", metadata["timestamp"]),
                            ("last_synced_at", synced_at),
                        ],
                    )
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
                finally:
                    connection.execute("DETACH DATABASE incoming")

            summary = {
                "version": metadata["version"],
                "sourceTimestamp": metadata["timestamp"],
                "variantCount": incoming_variants,
                "aliasCount": incoming_aliases,
                "added": added,
                "changed": changed,
                "removed": removed,
                "aliasesAdded": aliases_added,
                "aliasesChanged": aliases_changed,
                "aliasesRemoved": aliases_removed,
            }
            logger.info(
                "Updated Commander Spellbook database to %s: +%d ~%d -%d variants",
                metadata["version"],
                added,
                changed,
                removed,
            )
            return summary

    def matches(self, cards: list[dict[str, object]]) -> list[dict[str, object]]:
        """Return variants whose named card uses are present in the supplied deck.

        Template requirements are retained on each result but are not treated
        as verified card ingredients; callers can avoid using such conditional
        matches as definitive bracket signals.
        """
        self.ensure_initialized()
        available: dict[str, int] = {}
        for card in cards:
            name = card.get("name")
            quantity = card.get("quantity", 1)
            if isinstance(name, str) and isinstance(quantity, int) and quantity > 0:
                key = _normalize_name(name)
                available[key] = available.get(key, 0) + quantity
        if not available:
            return []

        with self._lock:
            connection = self._open(create=False)
            assert connection is not None
            placeholders = ",".join("?" for _ in available)
            candidates = connection.execute(
                "SELECT DISTINCT v.data FROM variants v "
                "JOIN variant_uses u ON u.variant_id = v.id "
                f"WHERE u.card_name IN ({placeholders})",
                tuple(available),
            ).fetchall()

        matches = []
        for (raw_variant,) in candidates:
            variant = json.loads(raw_variant)
            uses = _card_uses(variant)
            if not all(available.get(name, 0) >= quantity for name, quantity in uses.items()):
                continue
            produces = [
                item.get("feature", {}).get("name", "")
                for item in variant.get("produces", [])
                if isinstance(item, dict)
                and isinstance(item.get("feature"), dict)
                and isinstance(item.get("feature", {}).get("name"), str)
            ]
            produces_infinite = any("infinite" in name.casefold() for name in produces)
            requirements = [
                item.get("template", {}).get("name", "")
                for item in variant.get("requires", [])
                if isinstance(item, dict)
                and isinstance(item.get("template"), dict)
                and isinstance(item.get("template", {}).get("name"), str)
            ]
            matches.append(
                {
                    "id": variant["id"],
                    "uses": [
                        {"name": use.get("card", {}).get("name", ""), "quantity": use.get("quantity", 1)}
                        for use in variant.get("uses", [])
                    ],
                    "cardCount": sum(uses.values()),
                    "produces": [name for name in produces if name],
                    "producesInfinite": produces_infinite,
                    "description": variant.get("description", ""),
                    "requirements": [name for name in requirements if name],
                    "bracketTag": variant.get("bracketTag"),
                }
            )
        matches.sort(key=lambda combo: (combo["cardCount"], combo["id"]))
        return matches
