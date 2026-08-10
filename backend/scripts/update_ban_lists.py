#!/usr/bin/env python3
"""Sync hand-maintained format ban-list constants against live Scryfall data.

Every raw card object in the persistent `RawCardStore` (`data/scryfall_raw.db`
— see `scripts/import_bulk.py`/`update_card_pool.py`) already carries a full
per-format `legalities` dict; a hand-maintained ban-list constant like
`commander_legality.BANNED_COMMANDER_CARDS` is just a frozen snapshot of one
key of that dict at some point in the past. This script re-derives the live
snapshot and rewrites the constant in place — no network access of its own,
so run `update_card_pool.py` first if the raw store itself might be stale.

Adding a second format (once something in `game/`/`services/` actually
enforces that format's bans) is exactly one new `BAN_LIST_TARGETS` entry
below — nothing else here is format-specific. `update_card_pool.py`'s own
routine-refresh ban-list *report* reuses this module's registry too, so the
two never drift apart.

Usage (from backend/, venv active):
  python scripts/update_ban_lists.py                    # sync every registered format
  python scripts/update_ban_lists.py --format commander
  python scripts/update_ban_lists.py --dry-run           # print the diff, don't write
"""

from __future__ import annotations

import argparse
import ast
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mtg_analyzer.services.raw_card_store import RawCardStore  # noqa: E402

_BACKEND_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class BanListTarget:
    """Where a format's hand-maintained ban-list constant lives."""

    legality_key: str  # key into a Scryfall card's `legalities` dict, e.g. "commander"
    module_path: Path  # relative to backend/
    constant_name: str  # a module-level `NAME: frozenset[str] = frozenset({...})`


#: One entry per format this app actually checks bans for.
BAN_LIST_TARGETS: dict[str, BanListTarget] = {
    "commander": BanListTarget(
        legality_key="commander",
        module_path=Path("mtg_analyzer/services/commander_legality.py"),
        constant_name="BANNED_COMMANDER_CARDS",
    ),
}


def live_banned_names(cards: Iterable[dict], legality_key: str) -> set[str]:
    """Every card name whose raw Scryfall data reports 'banned' for one format.

    `cards` may be `RawCardStore.iter_raw()` or any plain list of raw card
    dicts (`update_card_pool.py` passes the dump it just downloaded, so its
    report reflects the fresh data before it's even merged into the store).
    """
    return {
        data["name"]
        for data in cards
        if (data.get("legalities") or {}).get(legality_key) == "banned"
    }


def current_constant_value(module_path: Path, constant_name: str) -> frozenset[str]:
    """Read a module-level `frozenset[str]` constant by parsing the source —
    not importing the module, so this has no dependency on the rest of
    `mtg_analyzer` being importable and can't execute unrelated module-level
    code."""
    node = _find_constant_node(module_path, constant_name)
    value = node.value
    if isinstance(value, ast.Call):
        value = value.args[0]
    return frozenset(ast.literal_eval(value))


def _find_constant_node(module_path: Path, constant_name: str) -> ast.AnnAssign:
    tree = ast.parse((_BACKEND_ROOT / module_path).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == constant_name
        ):
            return node
    sys.exit(f"could not find constant {constant_name!r} in {module_path}")


def _rewrite_constant(module_path: Path, constant_name: str, names: set[str]) -> None:
    full_path = _BACKEND_ROOT / module_path
    target = _find_constant_node(module_path, constant_name)
    lines = full_path.read_text(encoding="utf-8").splitlines(keepends=True)

    body = "".join(f"        {name!r},\n" for name in sorted(names, key=str.casefold))
    replacement = (
        f"{constant_name}: frozenset[str] = frozenset(\n"
        f"    {{\n"
        f"{body}"
        f"    }}\n"
        f")\n"
    )
    lines[target.lineno - 1 : target.end_lineno] = [replacement]
    full_path.write_text("".join(lines), encoding="utf-8")

    # Round-trip check: re-parse what was just written and confirm it matches
    # exactly, so a formatting bug in this script fails loudly, not silently.
    written = current_constant_value(module_path, constant_name)
    if written != frozenset(names):
        sys.exit(
            f"rewrite of {constant_name} in {module_path} did not round-trip "
            "— aborting, please inspect the file"
        )


def sync_format(store: RawCardStore, format_key: str, target: BanListTarget, dry_run: bool) -> bool:
    """Returns True iff there was drift (applied unless dry_run)."""
    live = live_banned_names(store.iter_raw(), target.legality_key)
    current = current_constant_value(target.module_path, target.constant_name)
    added = sorted(live - current, key=str.casefold)
    removed = sorted(current - live, key=str.casefold)
    if not added and not removed:
        print(f"{format_key}: no drift ({len(current)} banned cards, matches Scryfall).")
        return False

    print(
        f"{format_key}: {len(added)} newly banned, {len(removed)} no longer banned "
        f"(vs {target.constant_name} in {target.module_path}):"
    )
    for name in added:
        print(f"  + {name}")
    for name in removed:
        print(f"  - {name}")

    if dry_run:
        print(f"  (--dry-run: not writing {target.module_path})")
    else:
        _rewrite_constant(target.module_path, target.constant_name, live)
        print(f"  Updated {target.constant_name} in {target.module_path} ({len(live)} entries).")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--format", action="append", dest="formats", choices=sorted(BAN_LIST_TARGETS),
        help="only sync this format (repeatable); default: every registered format",
    )
    parser.add_argument("--dry-run", action="store_true", help="print the diff, don't write the source file")
    args = parser.parse_args()

    store = RawCardStore()
    if store.count() == 0:
        sys.exit("raw card store is empty — run scripts/update_card_pool.py or import_bulk.py first")

    formats = args.formats or sorted(BAN_LIST_TARGETS)
    any_drift = False
    for format_key in formats:
        any_drift |= sync_format(store, format_key, BAN_LIST_TARGETS[format_key], args.dry_run)
    store.close()

    if any_drift and not args.dry_run:
        print(
            "\nRe-run `python -m pytest -q` before committing — a ban-list change can "
            "flip existing deck-legality test fixtures."
        )


if __name__ == "__main__":
    main()
