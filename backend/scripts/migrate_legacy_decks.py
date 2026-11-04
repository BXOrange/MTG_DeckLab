#!/usr/bin/env python3
"""Legacy-store ownership migration (PLR-9b, plan §4 *Migration*).

Run by the OS operator on the server host, **once, with the server stopped**, as part of the
account-system cutover (PLR-9e); it must complete before enforcement is switched on for a real
install. Every deck saved before accounts existed becomes a **global** deck (nobody owns it;
players copy it into a private one to edit). IDs, metadata and cached derived fields are kept.

  python scripts/migrate_legacy_decks.py preview  [--data-dir DIR]   # read-only plan and report
  python scripts/migrate_legacy_decks.py apply    [--data-dir DIR] [--assign-assets-by-name]
  python scripts/migrate_legacy_decks.py restore  --backup DIR --yes [--data-dir DIR]

How `apply` stays safe:

1. **Own backup.** Each legacy store (decks, player assets) is copied with SQLite's online backup
   API into ``<data-dir>/migration/backup-<UTC stamp>/`` and verified (integrity check plus a
   content digest equal to the live store). It never relies on an operator-held backup; if a
   backup cannot be verified the command aborts before touching anything.
2. **Verified copy first.** The migration runs on a copy of the backup and the result is verified
   (same ids, names, timestamps and blobs; every classifiable row global; every other row still
   ``unassigned``). Only then is the same change applied to the live store, one transaction per
   store, and verified again against the copy.
3. **Resumable journal.** ``<data-dir>/migration/journal.json`` records each finished step, so a
   crash or a failed verification can simply be re-run: finished steps are skipped (re-verified),
   the rest continue. Running it again after success changes nothing (idempotent).
4. **Nothing is silently reassigned.** A row that cannot be classified (unreadable or inconsistent
   blob) stays ``unassigned`` -- invisible to every API -- and is listed in the report. The
   player-assets store gets the same treatment for PLR-16: its tables are rebuilt with an owner
   column (rows kept byte-for-byte, owner NULL = unassigned = invisible), and a legacy row is
   assigned to an account **only** with ``--assign-assets-by-name`` and only when its profile name
   matches exactly one existing player account (normalized as AccountStore does). Without the
   flag nothing is assigned: legacy asset names were free text anyone could type, so a stranger
   who registered the same name must not inherit someone's uploads without the operator
   deciding so. Unassigned names are listed in the report with their row counts.

Restore: stop the server, then ``restore --backup <dir> --yes`` (or copy the ``*.db`` files from the
backup directory over the live ones and delete any ``-wal``/``-shm`` siblings).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mtg_analyzer import config  # noqa: E402
from mtg_analyzer.services.account_store import ROLE_PLAYER, normalize_name  # noqa: E402
from mtg_analyzer.services.deck_database import (  # noqa: E402
    SCOPE_GLOBAL,
    SCOPE_UNASSIGNED,
    DeckDatabase,
)
from mtg_analyzer.services.player_assets import (  # noqa: E402
    _LEGACY_COPY_COLUMNS,
    ASSET_TABLES,
    PlayerAssetStore,
)

DECKS_STORE = "decks"
ASSETS_STORE = "assets"
STORE_FILES = {DECKS_STORE: "decks.db", ASSETS_STORE: "player_assets.db"}
ACCOUNTS_FILE = "accounts.db"

#: Journal steps per store, in order.
STEP_BACKUP = "backup"
STEP_WORKCOPY = "workcopy"
STEP_APPLIED = "applied"

#: The columns that exist before PLR-9b; the content digest only covers these, so it is the same
#: before and after the additive scope/owner columns arrive.
_LEGACY_DECK_COLUMNS = "id, name, created_at, data"


class MigrationError(Exception):
    """A verification or precondition failed; nothing further was changed."""


@dataclass
class Unclassifiable:
    deck_id: str
    reason: str


@dataclass
class StorePlan:
    store: str
    present: bool
    total: int = 0
    to_global: list[str] = field(default_factory=list)
    already_global: int = 0
    unclassifiable: list[Unclassifiable] = field(default_factory=list)
    foreign_private: int = 0  # rows already private (a store that was already migrated/used)


# -- low-level helpers ----------------------------------------------------------------------


def _connect(path: Path, *, read_only: bool = False) -> sqlite3.Connection:
    if read_only:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    return sqlite3.connect(str(path))


def _has_table(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def _digest(path: Path, store: str) -> str:
    """Content digest of a store that ignores the columns/rows this migration adds."""
    conn = _connect(path, read_only=True)
    try:
        h = hashlib.sha256()
        if store == DECKS_STORE:
            if _has_table(conn, "decks"):
                for row in conn.execute(f"SELECT {_LEGACY_DECK_COLUMNS} FROM decks ORDER BY id"):
                    h.update(json.dumps(row, ensure_ascii=False).encode("utf-8"))
        else:
            # Legacy content only (name + the columns that existed before PLR-16), identical for the
            # old name-keyed shape and the rebuilt owner-column shape.
            for table in ASSET_TABLES:
                if not _has_table(conn, table):
                    continue
                name_col = _asset_name_column(conn, table)
                columns = _LEGACY_COPY_COLUMNS[table]
                key = ASSET_TABLES[table]
                query = (f"SELECT {name_col}, {columns} FROM {table} WHERE {name_col} IS NOT NULL "
                         f"ORDER BY {name_col}, {key}")
                h.update(table.encode())
                for row in conn.execute(query):
                    h.update(json.dumps(row, ensure_ascii=False, default=lambda b: b.hex()).encode("utf-8"))
        return h.hexdigest()
    finally:
        conn.close()


def _integrity_ok(path: Path) -> bool:
    conn = _connect(path, read_only=True)
    try:
        return conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        conn.close()


def _classify_row(deck_id: str, data: str) -> Optional[str]:
    """The reason a row cannot be classified, or None when it is a well-formed legacy deck."""
    if not deck_id:
        return "empty id"
    try:
        blob = json.loads(data)
    except (TypeError, ValueError):
        return "unreadable data blob"
    if not isinstance(blob, dict):
        return "data blob is not an object"
    if blob.get("id") not in (None, deck_id):
        return "blob id differs from the row id"
    return None


def plan_decks(path: Path) -> StorePlan:
    plan = StorePlan(DECKS_STORE, present=path.exists())
    if not plan.present:
        return plan
    conn = _connect(path, read_only=True)
    try:
        if not _has_table(conn, "decks"):
            return plan
        columns = {r[1] for r in conn.execute("PRAGMA table_info(decks)")}
        select = "id, data, scope" if "scope" in columns else "id, data, NULL"
        for deck_id, data, scope in conn.execute(f"SELECT {select} FROM decks ORDER BY id"):
            plan.total += 1
            if scope == SCOPE_GLOBAL:
                plan.already_global += 1
            elif scope == "private":
                plan.foreign_private += 1
            else:
                reason = _classify_row(deck_id, data)
                if reason:
                    plan.unclassifiable.append(Unclassifiable(deck_id, reason))
                else:
                    plan.to_global.append(deck_id)
    finally:
        conn.close()
    return plan


def _promote(path: Path, deck_ids: list[str]) -> int:
    """Open a decks store (adding the additive columns), then make ``deck_ids`` global in ONE transaction."""
    DeckDatabase(path).close()  # runs the versioned migration; legacy rows land as `unassigned`
    conn = sqlite3.connect(str(path), isolation_level=None)
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            changed = 0
            for deck_id in deck_ids:
                changed += conn.execute(
                    "UPDATE decks SET scope = ?, owner = NULL WHERE id = ? AND scope = ?",
                    (SCOPE_GLOBAL, deck_id, SCOPE_UNASSIGNED),
                ).rowcount
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        return changed
    finally:
        conn.close()


def _verify_decks(path: Path, expected_digest: str, plan: StorePlan) -> None:
    if not _integrity_ok(path):
        raise MigrationError(f"{path.name}: integrity check failed")
    if _digest(path, DECKS_STORE) != expected_digest:
        raise MigrationError(f"{path.name}: deck content changed during migration")
    conn = _connect(path, read_only=True)
    try:
        scopes = dict(conn.execute("SELECT id, scope FROM decks"))
        owners = conn.execute("SELECT COUNT(*) FROM decks WHERE scope != 'private' AND owner IS NOT NULL").fetchone()[0]
    finally:
        conn.close()
    wrong = [i for i in plan.to_global if scopes.get(i) != SCOPE_GLOBAL]
    left_behind = [u.deck_id for u in plan.unclassifiable if scopes.get(u.deck_id) != SCOPE_UNASSIGNED]
    if wrong or left_behind or owners:
        raise MigrationError(f"{path.name}: classification verification failed")


# -- player assets (PLR-16) -------------------------------------------------------------------


@dataclass
class AssetPlan(StorePlan):
    """Legacy asset rows by profile name. ``assign`` maps a legacy name to the account that gets it."""

    assign: dict[str, str] = field(default_factory=dict)  # legacy name -> player_uuid
    expected: dict[str, str] = field(default_factory=dict)  # legacy name -> its account, assigned now or earlier
    assign_rows: dict[str, int] = field(default_factory=dict)  # legacy name -> rows it covers
    unassigned: dict[str, int] = field(default_factory=dict)  # legacy name -> row count left behind
    matched_not_enabled: dict[str, int] = field(default_factory=dict)  # name matches an account, flag off
    already_owned: int = 0
    assign_enabled: bool = False
    conflicts: int = 0  # rows left unassigned because the target account already owns that key


def _asset_name_column(conn: sqlite3.Connection, table: str) -> str:
    return "legacy_name" if "legacy_name" in {r[1] for r in conn.execute(f"PRAGMA table_info({table})")} else "player_name"


def _account_names(data_dir: Path) -> dict[str, list[str]]:
    """normalized name -> player account uuids (a list so a duplicate would be visible, not silent)."""
    path = data_dir / ACCOUNTS_FILE
    names: dict[str, list[str]] = {}
    if not path.exists():
        return names
    conn = _connect(path, read_only=True)
    try:
        for uuid, name_norm in conn.execute("SELECT player_uuid, name_norm FROM accounts WHERE role = ?", (ROLE_PLAYER,)):
            names.setdefault(name_norm, []).append(uuid)
    finally:
        conn.close()
    return names


def plan_assets(path: Path, accounts: dict[str, list[str]], *, assign_enabled: bool) -> AssetPlan:
    plan = AssetPlan(ASSETS_STORE, present=path.exists(), assign_enabled=assign_enabled)
    if not plan.present:
        return plan
    conn = _connect(path, read_only=True)
    try:
        for table in ASSET_TABLES:
            if not _has_table(conn, table):
                continue
            name_col = _asset_name_column(conn, table)
            owner = "owner_uuid" if name_col == "legacy_name" else "NULL"
            for name, owner_uuid, count in conn.execute(
                f"SELECT {name_col}, {owner}, COUNT(*) FROM {table} GROUP BY {name_col}, {owner}"
            ):
                plan.total += count
                if name is None:  # written by the running app after the schema upgrade: owned, never legacy
                    plan.already_owned += count
                    continue
                matches = accounts.get(normalize_name(name), [])
                if owner_uuid is not None:
                    plan.already_owned += count
                    if len(matches) == 1 and assign_enabled:
                        plan.expected[name] = matches[0]
                    continue
                if len(matches) == 1 and assign_enabled:
                    plan.assign[name] = matches[0]
                    plan.expected[name] = matches[0]
                    plan.assign_rows[name] = plan.assign_rows.get(name, 0) + count
                else:
                    plan.unassigned[name] = plan.unassigned.get(name, 0) + count
                    if len(matches) == 1:
                        plan.matched_not_enabled[name] = plan.matched_not_enabled.get(name, 0) + count
    finally:
        conn.close()
    return plan


def _assign_assets(path: Path, assign: dict[str, str]) -> None:
    """Open the store (running its schema migration), then assign the planned names in ONE transaction."""
    PlayerAssetStore(path).close()
    conn = sqlite3.connect(str(path), isolation_level=None)
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            for name, owner_uuid in assign.items():
                for table in ASSET_TABLES:
                    # OR IGNORE: a key the account already owns stays unassigned (reported, never overwritten).
                    conn.execute(
                        f"UPDATE OR IGNORE {table} SET owner_uuid = ? WHERE owner_uuid IS NULL AND legacy_name = ?",
                        (owner_uuid, name),
                    )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()


def _verify_assets(path: Path, expected_digest: str, assign: dict[str, str]) -> int:
    """Check digest, integrity and ownership; return the number of rows left unassigned by key conflicts."""
    if not _integrity_ok(path):
        raise MigrationError(f"{path.name}: integrity check failed")
    if _digest(path, ASSETS_STORE) != expected_digest:
        raise MigrationError(f"{path.name}: asset content changed during migration")
    conn = _connect(path, read_only=True)
    conflicts = 0
    try:
        for table in ASSET_TABLES:
            for name, owner_uuid, count in conn.execute(
                f"SELECT legacy_name, owner_uuid, COUNT(*) FROM {table} WHERE legacy_name IS NOT NULL "
                f"GROUP BY legacy_name, owner_uuid"
            ):
                if name in assign:
                    if owner_uuid is None:
                        conflicts += count
                    elif owner_uuid != assign[name]:
                        raise MigrationError(f"{path.name}: {name!r} assigned to the wrong account")
                elif owner_uuid is not None:
                    raise MigrationError(f"{path.name}: {name!r} was assigned but is not in the plan")
    finally:
        conn.close()
    return conflicts


# -- journal ----------------------------------------------------------------------------------


class Journal:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.data: dict = json.loads(path.read_text()) if path.exists() else {"backup_dir": None, "steps": {}}

    def done(self, store: str, step: str) -> bool:
        return self.data["steps"].get(f"{store}:{step}", False)

    def mark(self, store: str, step: str) -> None:
        self.data["steps"][f"{store}:{step}"] = True
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2))
        tmp.replace(self.path)  # atomic: a crash never leaves a half-written journal


# -- the command ------------------------------------------------------------------------------


@dataclass
class Report:
    plans: dict[str, StorePlan]
    backup_dir: Optional[Path] = None
    applied: bool = False
    skipped_stores: list[str] = field(default_factory=list)

    def text(self) -> str:
        lines = []
        for store, plan in self.plans.items():
            if not plan.present:
                lines.append(f"{store}: no store file (nothing to migrate)")
                continue
            if isinstance(plan, AssetPlan):
                lines.extend(_asset_report_lines(plan))
                continue
            lines.append(
                f"{store}: {plan.total} rows; {len(plan.to_global)} -> global, {plan.already_global} already global, "
                f"{plan.foreign_private} private (untouched), {len(plan.unclassifiable)} unclassifiable"
            )
            for bad in plan.unclassifiable:
                lines.append(f"  UNASSIGNED (invisible, needs manual review): {bad.deck_id}: {bad.reason}")
        if self.backup_dir:
            lines.append(f"backup: {self.backup_dir}")
        return "\n".join(lines)


def _asset_report_lines(plan: AssetPlan) -> list[str]:
    lines = [
        f"{plan.store}: {plan.total} rows; {0 if plan.conflicts else len(plan.assign)} legacy name(s) -> account, {plan.already_owned} already owned, "
        f"{sum(plan.unassigned.values())} unassigned row(s) under {len(plan.unassigned)} name(s)"
        + (f", {plan.conflicts} left over by key conflicts" if plan.conflicts else "")
    ]
    for name, uuid in sorted(plan.assign.items()):
        if plan.conflicts:
            lines.append(f"  LEFT UNASSIGNED (account already owns the same key): {name!r}: {plan.assign_rows[name]} row(s)")
        else:
            lines.append(f"  ASSIGN {name!r} -> account {uuid} ({plan.assign_rows[name]} row(s))")
    for name, count in sorted(plan.unassigned.items()):
        note = (" (matches an account; rerun with --assign-assets-by-name to assign)"
                if name in plan.matched_not_enabled else " (no unique matching account)")
        lines.append(f"  UNASSIGNED (invisible, needs manual review): {name!r}: {count} row(s){note}")
    return lines


def _stores(data_dir: Path) -> dict[str, Path]:
    return {store: data_dir / name for store, name in STORE_FILES.items()}


def preview(data_dir: Path, *, assign_assets_by_name: bool = False) -> Report:
    """Read-only: what `apply` would do. Opens the live stores read-only."""
    paths = _stores(data_dir)
    plans: dict[str, StorePlan] = {DECKS_STORE: plan_decks(paths[DECKS_STORE])}
    plans[ASSETS_STORE] = plan_assets(
        paths[ASSETS_STORE], _account_names(data_dir), assign_enabled=assign_assets_by_name
    )
    return Report(plans)


def _backup_store(source: Path, target: Path) -> None:
    src = _connect(source, read_only=True)
    dst = sqlite3.connect(str(target))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def apply(
    data_dir: Path,
    *,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    after_step: Optional[Callable[[str, str], None]] = None,
    assign_assets_by_name: bool = False,
) -> Report:
    """Back up, verify, migrate. ``after_step(store, step)`` is a test hook for simulated crashes."""
    paths = _stores(data_dir)
    journal = Journal(data_dir / "migration" / "journal.json")
    if journal.data["backup_dir"] is None:
        stamp = clock().strftime("%Y%m%dT%H%M%SZ")
        journal.data["backup_dir"] = str(data_dir / "migration" / f"backup-{stamp}")
        journal.save()
    # The policy chosen on the first run sticks: a resumed run must not flip it half-way.
    chosen = journal.data.setdefault("assign_assets_by_name", assign_assets_by_name)
    if chosen != assign_assets_by_name:
        raise MigrationError(
            "this migration was started with assign_assets_by_name="
            f"{chosen}; rerun with the same option or restore and remove the journal to start over"
        )
    journal.save()
    backup_dir = Path(journal.data["backup_dir"])
    work_dir = backup_dir / "work"
    work_dir.mkdir(parents=True, exist_ok=True)
    report = Report(preview(data_dir, assign_assets_by_name=assign_assets_by_name).plans, backup_dir=backup_dir)

    def step_done(store: str, step: str) -> None:
        journal.mark(store, step)
        if after_step:
            after_step(store, step)

    for store, live in paths.items():
        if not live.exists():
            report.skipped_stores.append(store)
            continue
        backup, work = backup_dir / STORE_FILES[store], work_dir / STORE_FILES[store]
        # 1. Own, verified backup. Re-verified on every run so a resumed run never trusts a stale file.
        if not journal.done(store, STEP_BACKUP):
            live_digest = _digest(live, store)
            _backup_store(live, backup)
            if not _integrity_ok(backup) or _digest(backup, store) != live_digest:
                raise MigrationError(f"{store}: backup could not be verified; nothing was changed")
            step_done(store, STEP_BACKUP)
        elif not backup.exists() or not _integrity_ok(backup):
            raise MigrationError(f"{store}: recorded backup is missing or damaged; remove the journal to start over")
        baseline = _digest(backup, store)

        if store == ASSETS_STORE:
            accounts = _account_names(data_dir)
            # 2. Migrate a copy of the backup first and verify the outcome.
            if not journal.done(store, STEP_WORKCOPY):
                shutil.copyfile(backup, work)
                planned = plan_assets(work, accounts, assign_enabled=assign_assets_by_name)
                _assign_assets(work, planned.assign)
                _verify_assets(work, baseline, planned.expected)
                step_done(store, STEP_WORKCOPY)
            # 3. Apply to the live store in one transaction, then verify it against the same expectation.
            if not journal.done(store, STEP_APPLIED):
                if _digest(live, store) != baseline:
                    raise MigrationError(f"{store}: live store changed after the backup (server running?)")
                live_plan = plan_assets(live, accounts, assign_enabled=assign_assets_by_name)
                _assign_assets(live, live_plan.assign)
                _verify_assets(live, baseline, live_plan.expected)
                step_done(store, STEP_APPLIED)
            continue

        plan = plan_decks(backup)
        # 2. Migrate a copy of the backup first and verify the outcome.
        if not journal.done(store, STEP_WORKCOPY):
            shutil.copyfile(backup, work)
            _promote(work, plan.to_global)
            _verify_decks(work, baseline, plan)
            step_done(store, STEP_WORKCOPY)
        # 3. Apply to the live store in one transaction, then verify it against the same expectation.
        if not journal.done(store, STEP_APPLIED):
            if _digest(live, store) != baseline:
                raise MigrationError(f"{store}: live store changed after the backup (server running?)")
            live_plan = plan_decks(live)
            _promote(live, live_plan.to_global)
            _verify_decks(live, baseline, live_plan)
            step_done(store, STEP_APPLIED)
        # (A finished store is not re-verified: the live data legitimately changes once the server runs.)
    report.applied = True
    # What is left after the run: names still holding NULL-owner rows. With the flag on, a name that
    # is still plannable means the account already owned the same key (a conflict), never overwritten.
    final_assets = plan_assets(paths[ASSETS_STORE], _account_names(data_dir), assign_enabled=assign_assets_by_name)
    final_assets.conflicts = sum(final_assets.assign_rows.values())
    report.plans = {
        DECKS_STORE: plan_decks(paths[DECKS_STORE]),
        ASSETS_STORE: final_assets,
    }
    return report


def restore(data_dir: Path, backup_dir: Path) -> list[str]:
    """Copy the verified backups back over the live stores (server must be stopped)."""
    restored = []
    for store, live in _stores(data_dir).items():
        saved = backup_dir / STORE_FILES[store]
        if not saved.exists():
            continue
        if not _integrity_ok(saved):
            raise MigrationError(f"{saved} is damaged; not restoring")
        for suffix in ("-wal", "-shm"):
            Path(str(live) + suffix).unlink(missing_ok=True)
        shutil.copyfile(saved, live)
        restored.append(store)
    (data_dir / "migration" / "journal.json").unlink(missing_ok=True)
    return restored


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["preview", "apply", "restore"])
    parser.add_argument("--data-dir", type=Path, default=None, help="default: MTG_DATA_DIR / config.DATA_DIR")
    parser.add_argument("--backup", type=Path, help="restore: the backup-<stamp> directory")
    parser.add_argument("--assign-assets-by-name", action="store_true",
                        help="assign a legacy asset name to the one player account with that exact (normalized) name")
    parser.add_argument("--yes", action="store_true", help="restore: confirm overwriting the live stores")
    args = parser.parse_args(argv)
    data_dir = args.data_dir or config.DATA_DIR
    try:
        if args.command == "preview":
            print(preview(data_dir, assign_assets_by_name=args.assign_assets_by_name).text())
        elif args.command == "apply":
            report = apply(data_dir, assign_assets_by_name=args.assign_assets_by_name)
            print(report.text())
            print(f"\nDone. To undo: stop the server, then\n  python scripts/migrate_legacy_decks.py restore --backup {report.backup_dir} --yes")
        else:
            if not args.backup or not args.yes:
                print("restore needs --backup DIR and --yes", file=sys.stderr)
                return 2
            print("restored:", ", ".join(restore(data_dir, args.backup)) or "nothing")
    except MigrationError as exc:
        print(f"ABORTED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
