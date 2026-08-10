#!/usr/bin/env python3
"""Read-only inspector for this project's five SQLite stores.

Resolves each store's on-disk path from the same service modules the app
itself uses (`card_database.py`, `raw_card_store.py`, `coverage_db.py`,
`deck_database.py`, `player_assets.py`) rather than hard-coding paths, so it
never drifts from `MTG_CACHE_DIR`/`MTG_DATA_DIR` overrides and stays correct
if a default path ever moves.

Every connection is opened `mode=ro` (SQLite's own read-only guard) and the
`sql` subcommand additionally refuses anything but SELECT/WITH/PRAGMA/EXPLAIN
before that — this tool is for looking, never for fixing data. A write
belongs in the owning service class, which enforces invariants (unique-name
indexes, content-hash keys, preserved-on-omission fields) raw SQL doesn't
know about.

Subcommands
  list                    every known store: path, exists?, per-table row counts
  schema <db>             CREATE TABLE/INDEX statements for one store
  sql <db> <SELECT ...>   run a read-only query, print an aligned table
  card <name>             decoded convenience lookup in cards.db
  coverage <name>         decoded convenience lookup in coverage.db

Usage (from backend/, venv active — or via the wrapper paths in SKILL.md):
  python <this> list
  python <this> schema coverage
  python <this> card "Lightning Bolt"
  python <this> coverage "Frodo, Sauron's Bane"
  python <this> sql decks "SELECT id, name FROM decks ORDER BY created_at DESC LIMIT 10"
  python <this> sql cards "SELECT name FROM cards WHERE name LIKE '%Bolt%'" --limit 50 --full
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

#: Cell width before truncation in table output (see --full).
_DEFAULT_CELL_WIDTH = 100
#: Default row cap for `sql` so an unbounded SELECT can't dump a whole table.
_DEFAULT_ROW_LIMIT = 200


# backend/ on the path — this script lives under .claude/skills/, outside the
# package tree, so walk up to the repo root and take `backend/` from there
# (also honouring an explicit MTG_BACKEND_DIR for an out-of-tree checkout).
def _find_backend() -> Path:
    env = os.environ.get("MTG_BACKEND_DIR")
    if env:
        return Path(env).resolve()
    here = Path(__file__).resolve()
    for parent in [Path.cwd().resolve(), *Path.cwd().resolve().parents, *here.parents]:
        if (parent / "mtg_analyzer").is_dir():
            return parent
        if (parent / "backend" / "mtg_analyzer").is_dir():
            return parent / "backend"
    sys.exit("could not locate backend/ — run from the repo, or set MTG_BACKEND_DIR")


sys.path.insert(0, str(_find_backend()))

from mtg_analyzer.services.card_database import DEFAULT_DB_PATH as CARDS_DB  # noqa: E402
from mtg_analyzer.services.coverage_db import DEFAULT_COVERAGE_DB_PATH as COVERAGE_DB  # noqa: E402
from mtg_analyzer.services.deck_database import DEFAULT_DECKS_DB_PATH as DECKS_DB  # noqa: E402
from mtg_analyzer.services.player_assets import (  # noqa: E402
    DEFAULT_PLAYER_ASSETS_DB_PATH as PLAYER_ASSETS_DB,
)
from mtg_analyzer.services.raw_card_store import DEFAULT_RAW_STORE_PATH as RAW_CARDS_DB  # noqa: E402

#: name -> (path, one-line description). Kept in sync with the reference/*.md
#: files under this skill — each name here has a matching reference doc.
REGISTRY: dict[str, tuple[Path, str]] = {
    "cards": (CARDS_DB, "card cache — one row per unique card name (disposable)"),
    "raw-cards": (RAW_CARDS_DB, "untouched raw Scryfall JSON, keyed by oracle_id"),
    "coverage": (COVERAGE_DB, "parser MODELED/UNMODELED/AUTHORED coverage ledger"),
    "decks": (DECKS_DB, "saved decks (real user data)"),
    "player-assets": (PLAYER_ASSETS_DB, "per-player token art / sleeves / favorites"),
}

_READ_ONLY_PREFIXES = ("select", "with", "pragma", "explain")


def _open_ro(path: Path) -> sqlite3.Connection:
    if not path.exists():
        sys.exit(f"no such database file: {path}\n(nothing has written to this store yet)")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _resolve(name: str) -> Path:
    if name not in REGISTRY:
        known = ", ".join(sorted(REGISTRY))
        sys.exit(f"unknown store {name!r} — known stores: {known}")
    return REGISTRY[name][0]


def _truncate(value: object, width: int) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bytes):
        return f"<{len(value)} bytes>"
    text = str(value)
    if width and len(text) > width:
        return text[: width - 1] + "…"
    return text


def _print_table(rows: list[sqlite3.Row], full: bool) -> None:
    if not rows:
        print("(0 rows)")
        return
    width = 0 if full else _DEFAULT_CELL_WIDTH
    columns = rows[0].keys()
    cells = [[_truncate(row[col], width) for col in columns] for row in rows]
    widths = [max(len(col), *(len(r[i]) for r in cells)) for i, col in enumerate(columns)]
    header = "  ".join(col.ljust(widths[i]) for i, col in enumerate(columns))
    print(header)
    print("  ".join("-" * w for w in widths))
    for row in cells:
        print("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)))
    print(f"({len(rows)} row{'s' if len(rows) != 1 else ''})")


def cmd_list(_args: argparse.Namespace) -> None:
    for name, (path, desc) in sorted(REGISTRY.items()):
        exists = path.exists()
        print(f"{name:<15} {desc}")
        print(f"{'':<15} {path}  [{'exists' if exists else 'not created yet'}]")
        if exists:
            conn = _open_ro(path)
            tables = [
                r["name"]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
            ]
            for table in sorted(tables):
                count = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
                print(f"{'':<15}   {table}: {count} rows")
            conn.close()
        print()


def cmd_schema(args: argparse.Namespace) -> None:
    path = _resolve(args.db)
    conn = _open_ro(path)
    rows = conn.execute(
        "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' "
        "ORDER BY type DESC, name"
    ).fetchall()
    for row in rows:
        print(row["sql"] + ";")
    conn.close()


def cmd_sql(args: argparse.Namespace) -> None:
    stripped = args.query.strip().lower()
    if not stripped.startswith(_READ_ONLY_PREFIXES):
        sys.exit(
            "refusing non-SELECT statement — this tool is read-only by design; "
            "writes belong in the owning service class (see SKILL.md)"
        )
    path = _resolve(args.db)
    conn = _open_ro(path)
    try:
        rows = conn.execute(args.query).fetchmany(args.limit)
    except sqlite3.Error as exc:
        sys.exit(f"sqlite error: {exc}")
    finally:
        conn.close()
    _print_table(rows, full=args.full)


def cmd_card(args: argparse.Namespace) -> None:
    conn = _open_ro(_resolve("cards"))
    row = conn.execute(
        "SELECT * FROM cards WHERE name = ? COLLATE NOCASE OR flavor_name = ? COLLATE NOCASE",
        (args.name, args.name),
    ).fetchone()
    conn.close()
    if row is None:
        sys.exit(f"not in cache: {args.name!r}")
    data = json.loads(row["data"])
    if args.full:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return
    fields = [
        "name", "flavor_name", "mana_cost_string", "converted_mana_cost",
        "type_line", "power", "toughness", "loyalty", "oracle_text",
        "keywords", "set_code", "rarity", "layout",
    ]
    for field in fields:
        value = data.get(field)
        if value in (None, "", []):
            continue
        print(f"{field}: {value}")
    print("\n(--full for the entire stored JSON blob)")


def cmd_coverage(args: argparse.Namespace) -> None:
    conn = _open_ro(_resolve("coverage"))
    rows = conn.execute(
        "SELECT * FROM card_coverage WHERE name = ? COLLATE NOCASE ORDER BY updated_at DESC",
        (args.name,),
    ).fetchall()
    conn.close()
    if not rows:
        sys.exit(f"no coverage row for: {args.name!r} (never measured, or name mismatch)")
    current, *stale = rows
    print(f"parser_version: {current['parser_version']}  (current)")
    print(f"coverage:       {current['coverage']}  (source: {current['source']}, covered: {bool(current['covered'])})")
    unclaimed = json.loads(current["unclaimed"])
    if unclaimed:
        print(f"unclaimed:      {unclaimed}")
    print(f"updated_at:     {current['updated_at']}")
    if stale:
        versions = ", ".join(str(r["parser_version"]) for r in stale[:8])
        more = f", … (+{len(stale) - 8} more)" if len(stale) > 8 else ""
        print(
            f"\n({len(stale)} stale row(s) under older parser_version: {versions}{more} "
            "— re-measured since, safe to ignore)"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="every known store: path, exists?, row counts").set_defaults(func=cmd_list)

    p_schema = sub.add_parser("schema", help="CREATE TABLE/INDEX statements for one store")
    p_schema.add_argument("db", choices=sorted(REGISTRY))
    p_schema.set_defaults(func=cmd_schema)

    p_sql = sub.add_parser("sql", help="run a read-only query")
    p_sql.add_argument("db", choices=sorted(REGISTRY))
    p_sql.add_argument("query")
    p_sql.add_argument("--full", action="store_true", help="don't truncate long cells")
    p_sql.add_argument("--limit", type=int, default=_DEFAULT_ROW_LIMIT)
    p_sql.set_defaults(func=cmd_sql)

    p_card = sub.add_parser("card", help="decoded convenience lookup in cards.db")
    p_card.add_argument("name")
    p_card.add_argument("--full", action="store_true", help="dump the entire stored JSON blob")
    p_card.set_defaults(func=cmd_card)

    p_coverage = sub.add_parser("coverage", help="decoded convenience lookup in coverage.db")
    p_coverage.add_argument("name")
    p_coverage.set_defaults(func=cmd_coverage)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
