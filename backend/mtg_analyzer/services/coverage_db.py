"""Persistent *engineering* database for the card-modeling pipeline.

Reference: docs/implementation-state/10_COMPLETION_ROADMAP.md (M1), and the
plan "Model all Edge Cases, the whole card database, and all ~30k MTG cards"
(Phase 0c). Design mirrors `services/card_database.py` (thread-safe SQLite,
`INSERT OR REPLACE`, indexed lookup columns + JSON blobs for the flexible parts).

Why this exists — and why it is *separate* from the card cache
--------------------------------------------------------------
The card cache (`cache/db/cards.db`) is disposable and is **wiped** by
`services/schema_version.reconcile_schema` on any `Card`-model drift, and
`parse_oracle`'s memoization is per-process only. Neither survives as an
engineering ledger of "which cards are already modeled and which templates are
already handled". This DB is that ledger. It lives under the *persistent*
`DATA_DIR` (never under `cache/`), so a full re-measure over ~30k cards never
re-does settled deterministic work:

* `card_coverage` — one row per card, keyed on the parser's own content
  signature (`gate._parse_cache_key`) **plus `PARSER_VERSION`**. A re-run only
  (re-)parses cards whose signature is missing or stale; bumping
  `PARSER_VERSION` invalidates exactly the affected rows.
* `snapshots` — a coverage number per run, so progress is tracked over time.
* `handled_templates` — which processing-list templates a handler now claims,
  the durable shared backlog ledger across waves / subagents / machines.

This is a pure engineering-side service: it may import `parser/oracle`, but
nothing in `parser/oracle` imports it (the front-end security boundary holds).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

from mtg_analyzer.config import DATA_DIR
from mtg_analyzer.parser.oracle.gate import PARSER_VERSION, _parse_cache_key

#: Scryfall `legalities.commander` values that count as "in the Commander
#: card pool" for measurement purposes. "restricted" is included for
#: completeness (Scryfall's vocabulary allows it for some formats) even
#: though Commander itself has no restricted list today; "banned"/
#: "not_legal" are excluded. Same field `scripts/update_ban_lists.py`'s
#: `live_banned_names` reads off `RawCardStore` raw data.
COMMANDER_LEGAL_STATUSES = frozenset({"legal", "restricted"})

#: Default on-disk location for the persistent engineering ledger. Under
#: DATA_DIR (persistent user/engineering data), NOT CACHE_DIR (disposable,
#: schema-wiped) — see module docstring.
DEFAULT_COVERAGE_DB_PATH = DATA_DIR / "coverage.db"

#: Verdict a card gets in the ledger. MODELED/UNMODELED/NEVER_SUPPORTED come
#: straight from the parser (`gate.ParseResult.coverage`, lowercased); AUTHORED
#: means the card is hand-registered in `ability_catalogue` and therefore
#: *behaves* even if the parser alone leaves it UNMODELED.
MODELED = "modeled"
UNMODELED = "unmodeled"
NEVER_SUPPORTED = "never_supported"
AUTHORED = "authored"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS card_coverage (
    content_hash   TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    coverage       TEXT NOT NULL,   -- parser verdict: 'modeled' | 'unmodeled' | 'never_supported'
    source         TEXT NOT NULL,   -- 'parser' | 'authored'
    covered        INTEGER NOT NULL,-- 1 if the card behaves (modeled OR authored)
    unclaimed      TEXT NOT NULL,   -- JSON list[str] of unclaimed clause seeds
    updated_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_card_coverage_name ON card_coverage (name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_card_coverage_covered ON card_coverage (covered);

CREATE TABLE IF NOT EXISTS snapshots (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    taken_at       TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    total          INTEGER NOT NULL,
    covered        INTEGER NOT NULL,
    fraction       REAL NOT NULL,
    top_templates  TEXT NOT NULL    -- JSON list[[template, cards]]
);

CREATE TABLE IF NOT EXISTS handled_templates (
    template   TEXT PRIMARY KEY,
    handler    TEXT NOT NULL DEFAULT '',
    handled_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def content_hash(card: object, parser_version: str = PARSER_VERSION) -> str:
    """Stable hash of the parser's content signature + PARSER_VERSION + whether
    the card is hand-`AUTHORED`.

    Uses `gate._parse_cache_key` so the ledger keys on *exactly* the fields the
    parser reads — a card whose text changes (or a parser-version bump) yields a
    new hash and is transparently re-measured, while an unchanged card is reused.

    The registration flag has to be part of the key because "covered" means
    parser-`MODELED` **or** hand-`AUTHORED` (`scripts/coverage_report.py`):
    hand-authoring a card in `game/ability_catalogue.py` changes its coverage
    without touching a single field the parser reads, so keying on the parse
    signature alone would silently reuse a stale "uncovered" row forever — and
    the only workaround would be bumping `PARSER_VERSION` for a change the
    parser had no part in, invalidating all 34k rows to re-measure a handful.
    """
    from ..game.ability_catalogue import is_registered  # function-scoped: import cycle

    authored = "1" if is_registered(getattr(card, "name", "") or "") else "0"
    key = (parser_version, authored) + tuple(str(part) for part in _parse_cache_key(card))
    return hashlib.sha1("␟".join(key).encode("utf-8")).hexdigest()


class CoverageRow:
    """A stored per-card coverage result (lightweight, not a dataclass on purpose)."""

    __slots__ = ("content_hash", "name", "parser_version", "coverage", "source", "covered", "unclaimed")

    def __init__(self, content_hash, name, parser_version, coverage, source, covered, unclaimed):
        self.content_hash = content_hash
        self.name = name
        self.parser_version = parser_version
        self.coverage = coverage
        self.source = source
        self.covered = bool(covered)
        self.unclaimed = unclaimed


class CoverageDatabase:
    """Persistent engineering ledger for card-modeling coverage."""

    def __init__(self, db_path: Union[str, Path] = DEFAULT_COVERAGE_DB_PATH) -> None:
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        # Same threading posture as CardDatabase: a single instance may be
        # touched from multiple threads, so serialize with a lock.
        self._connection = sqlite3.connect(str(db_path), check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            self._connection.executescript(_SCHEMA)
            self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "CoverageDatabase":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # -- per-card coverage ------------------------------------------------

    def get(self, chash: str) -> Optional[CoverageRow]:
        with self._lock:
            row = self._connection.execute(
                "SELECT content_hash, name, parser_version, coverage, source, covered, unclaimed "
                "FROM card_coverage WHERE content_hash = ?",
                (chash,),
            ).fetchone()
        if row is None:
            return None
        return CoverageRow(row[0], row[1], row[2], row[3], row[4], row[5], json.loads(row[6]))

    def upsert(
        self,
        chash: str,
        name: str,
        coverage: str,
        source: str,
        unclaimed: list[str],
        parser_version: str = PARSER_VERSION,
    ) -> None:
        covered = 1 if (source == "authored" or coverage == MODELED) else 0
        with self._lock:
            self._connection.execute(
                "INSERT OR REPLACE INTO card_coverage "
                "(content_hash, name, parser_version, coverage, source, covered, unclaimed, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (chash, name, parser_version, coverage, source, covered,
                 json.dumps(unclaimed), _now()),
            )
            self._connection.commit()

    def counts(self) -> tuple[int, int]:
        """(total, covered) rows currently in the ledger."""
        with self._lock:
            total = self._connection.execute("SELECT COUNT(*) FROM card_coverage").fetchone()[0]
            covered = self._connection.execute(
                "SELECT COUNT(*) FROM card_coverage WHERE covered = 1"
            ).fetchone()[0]
        return total, covered

    # -- snapshots --------------------------------------------------------

    def record_snapshot(
        self, total: int, covered: int, top_templates: list[tuple[str, int]]
    ) -> None:
        fraction = (covered / total) if total else 1.0
        with self._lock:
            self._connection.execute(
                "INSERT INTO snapshots "
                "(taken_at, parser_version, total, covered, fraction, top_templates) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (_now(), PARSER_VERSION, total, covered, fraction,
                 json.dumps([list(t) for t in top_templates])),
            )
            self._connection.commit()

    def latest_snapshots(self, limit: int = 10) -> list[dict]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT taken_at, parser_version, total, covered, fraction "
                "FROM snapshots ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {"taken_at": r[0], "parser_version": r[1], "total": r[2],
             "covered": r[3], "fraction": r[4]}
            for r in rows
        ]

    # -- handled-template ledger -----------------------------------------

    def mark_template_handled(self, template: str, handler: str = "") -> None:
        with self._lock:
            self._connection.execute(
                "INSERT OR REPLACE INTO handled_templates (template, handler, handled_at) "
                "VALUES (?, ?, ?)",
                (template, handler, _now()),
            )
            self._connection.commit()

    def handled_templates(self) -> dict[str, str]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT template, handler FROM handled_templates"
            ).fetchall()
        return {r[0]: r[1] for r in rows}


def commander_legal_names(store) -> set[str]:
    """Every card name whose raw Scryfall data reports it as part of the
    Commander card pool (`legalities.commander` in `COMMANDER_LEGAL_STATUSES`).

    `store` is a `RawCardStore` (or anything exposing `iter_raw()` yielding
    raw Scryfall dicts — same duck-typed usage as
    `scripts/update_ban_lists.py`'s `live_banned_names`, whose exact
    `legalities` field-reading pattern this mirrors). This is a name-set for
    ad-hoc measurement/filtering only — not a persistent table, and not the
    deck-level legality check in `commander_legality.py`, which is a
    different, structural concern.
    """
    return {
        data["name"]
        for data in store.iter_raw()
        if (data.get("legalities") or {}).get("commander") in COMMANDER_LEGAL_STATUSES
    }
