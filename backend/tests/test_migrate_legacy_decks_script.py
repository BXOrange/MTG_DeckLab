"""PLR-9b: the legacy-deck ownership migration command, on temporary copies only."""

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest

from mtg_analyzer.models.decks.deck import Deck
from mtg_analyzer.services.deck_database import DeckDatabase

_SPEC = importlib.util.spec_from_file_location(
    "migrate_legacy_decks", Path(__file__).resolve().parent.parent / "scripts" / "migrate_legacy_decks.py"
)
mig = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = mig  # dataclasses resolve their module through sys.modules
_SPEC.loader.exec_module(mig)

LEGACY_SCHEMA = """
CREATE TABLE decks (id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL, data TEXT NOT NULL);
CREATE INDEX idx_decks_created_at ON decks (created_at);
"""


def _legacy_decks(path, rows):
    conn = sqlite3.connect(path)
    conn.executescript(LEGACY_SCHEMA)
    for deck_id, name, data in rows:
        conn.execute("INSERT INTO decks VALUES (?, ?, '2024-01-01', ?)", (deck_id, name, data))
    conn.commit()
    conn.close()


def _good(deck_id, name="Deck", **extra):
    return (deck_id, name, json.dumps({"id": deck_id, "name": name, "mainboardText": "99 Forest", "createdAt": "2024-01-01", **extra}))


def _rows(path):
    conn = sqlite3.connect(path)
    try:
        return {r[0]: r[1:] for r in conn.execute("SELECT id, scope, owner, name, created_at, data FROM decks")}
    finally:
        conn.close()


@pytest.fixture
def data_dir(tmp_path):
    return tmp_path / "data"


def _install(data_dir, rows, assets=True):
    data_dir.mkdir()
    _legacy_decks(data_dir / "decks.db", rows)
    if assets:
        conn = sqlite3.connect(data_dir / "player_assets.db")
        conn.executescript("CREATE TABLE sleeves (id TEXT, owner_name TEXT); INSERT INTO sleeves VALUES ('s', 'Bernd');")
        conn.commit()
        conn.close()


def test_empty_install_has_nothing_to_do(data_dir):
    data_dir.mkdir()
    report = mig.apply(data_dir)
    assert report.applied and set(report.skipped_stores) == {"decks", "assets"}
    assert not (data_dir / "decks.db").exists()  # no store is created out of thin air


def test_preview_changes_nothing_on_disk(data_dir):
    _install(data_dir, [_good("a"), ("b", "Broken", "not json")])
    before = {p.name: p.read_bytes() for p in data_dir.iterdir()}
    report = mig.preview(data_dir)
    plan = report.plans["decks"]
    assert plan.total == 2 and plan.to_global == ["a"] and [u.deck_id for u in plan.unclassifiable] == ["b"]
    assert {p.name: p.read_bytes() for p in data_dir.iterdir()} == before
    assert not (data_dir / "migration").exists()


def test_legacy_decks_become_global_with_ids_metadata_and_caches_intact(data_dir):
    cached = _good("a", "Cached", colorIdentity=["G"], validationResult={"isLegal": True}, sleeveId="s", author="Me")
    _install(data_dir, [cached, _good("b")])
    legacy = {r[0]: r[1:] for r in sqlite3.connect(data_dir / "decks.db").execute("SELECT * FROM decks")}
    assert "scope" not in {r[1] for r in sqlite3.connect(data_dir / "decks.db").execute("PRAGMA table_info(decks)")}
    report = mig.apply(data_dir)
    assert report.applied
    after = _rows(data_dir / "decks.db")
    assert set(after) == {"a", "b"}
    for deck_id, (scope, owner, name, created, data) in after.items():
        assert (scope, owner) == ("global", None)
        assert (name, created, data) == legacy[deck_id]  # name, timestamp and blob byte-identical
    db = DeckDatabase(data_dir / "decks.db")
    deck = db.get_deck("a", "any-player")
    assert deck.color_identity == ["G"] and deck.validation_result == {"isLegal": True}
    assert deck.sleeve_id == "s" and deck.author == "Me" and deck.created_at == "2024-01-01"


def test_unclassifiable_rows_stay_unassigned_invisible_and_reported(data_dir):
    _install(data_dir, [_good("ok"), ("bad1", "x", "not json"), ("bad2", "y", "[1]"), ("bad3", "z", json.dumps({"id": "other"}))])
    report = mig.apply(data_dir)
    assert {u.deck_id for u in report.plans["decks"].unclassifiable} == {"bad1", "bad2", "bad3"}
    assert "UNASSIGNED" in report.text()
    assert "bad1" in report.text() and "unreadable" in report.text()
    rows = _rows(data_dir / "decks.db")
    assert rows["ok"][0] == "global"
    assert all(rows[i][0] == "unassigned" for i in ("bad1", "bad2", "bad3"))
    db = DeckDatabase(data_dir / "decks.db")
    assert [d.id for d in db.list_decks("p")] == ["ok"]
    assert db.get_deck("bad1", "p") is None


def test_backup_is_taken_verified_and_restorable(data_dir):
    _install(data_dir, [_good("a")])
    report = mig.apply(data_dir)
    backup = report.backup_dir / "decks.db"
    assert backup.exists() and (report.backup_dir / "player_assets.db").exists()
    assert "scope" not in {r[1] for r in sqlite3.connect(backup).execute("PRAGMA table_info(decks)")}
    assert mig.restore(data_dir, report.backup_dir) == ["decks", "assets"]
    conn = sqlite3.connect(data_dir / "decks.db")
    assert [r[0] for r in conn.execute("SELECT id FROM decks")] == ["a"]
    assert "scope" not in {r[1] for r in conn.execute("PRAGMA table_info(decks)")}


def test_unverifiable_backup_aborts_before_any_change(data_dir, monkeypatch):
    _install(data_dir, [_good("a")])
    live_before = (data_dir / "decks.db").read_bytes()
    monkeypatch.setattr(mig, "_integrity_ok", lambda path: False)
    with pytest.raises(mig.MigrationError, match="backup could not be verified"):
        mig.apply(data_dir)
    assert (data_dir / "decks.db").read_bytes() == live_before
    assert mig.main(["apply", "--data-dir", str(data_dir)]) == 1


def test_a_backup_that_differs_from_the_live_store_aborts(data_dir, monkeypatch):
    _install(data_dir, [_good("a")])
    real = mig._backup_store

    def corrupting(source, target):
        real(source, target)
        conn = sqlite3.connect(target)
        conn.execute("DELETE FROM decks")
        conn.commit()
        conn.close()

    monkeypatch.setattr(mig, "_backup_store", corrupting)
    with pytest.raises(mig.MigrationError, match="backup could not be verified"):
        mig.apply(data_dir)
    conn = sqlite3.connect(data_dir / "decks.db")
    assert conn.execute("SELECT COUNT(*) FROM decks").fetchone()[0] == 1
    assert "scope" not in {r[1] for r in conn.execute("PRAGMA table_info(decks)")}


class _Crash(Exception):
    pass


@pytest.mark.parametrize("crash_at", [("decks", "backup"), ("decks", "workcopy"), ("decks", "applied")])
def test_partial_failure_resumes_from_the_journal(data_dir, crash_at):
    _install(data_dir, [_good("a"), _good("b")])

    def crash(store, step):
        if (store, step) == crash_at:
            raise _Crash

    with pytest.raises(_Crash):
        mig.apply(data_dir, after_step=crash)
    journal = json.loads((data_dir / "migration" / "journal.json").read_text())
    assert journal["steps"][f"{crash_at[0]}:{crash_at[1]}"] is True
    report = mig.apply(data_dir)  # restart
    assert report.applied
    assert {r[0] for r in _rows(data_dir / "decks.db").values()} == {"global"}
    assert len(list((data_dir / "migration").glob("backup-*"))) == 1  # the same backup is reused


def test_repeat_execution_changes_nothing(data_dir):
    _install(data_dir, [_good("a"), ("bad", "x", "nope")])
    mig.apply(data_dir)
    first = _rows(data_dir / "decks.db")
    # the server runs for a while: a player-created deck now exists
    db = DeckDatabase(data_dir / "decks.db")
    db.save_private(Deck(name="New"), "uuid-1")
    db.close()
    mig.apply(data_dir)
    again = _rows(data_dir / "decks.db")
    assert {k: v for k, v in again.items() if k in first} == first
    assert len(again) == 3
    assert len(list((data_dir / "migration").glob("backup-*"))) == 1


def test_cli_preview_apply_restore(data_dir, capsys):
    _install(data_dir, [_good("a")])
    assert mig.main(["preview", "--data-dir", str(data_dir)]) == 0
    assert "1 -> global" in capsys.readouterr().out
    assert mig.main(["apply", "--data-dir", str(data_dir)]) == 0
    out = capsys.readouterr().out
    assert "restore --backup" in out
    backup = Path(out.split("--backup ")[1].split(" --yes")[0])
    assert mig.main(["restore", "--backup", str(backup), "--data-dir", str(data_dir)]) == 2  # needs --yes
    assert mig.main(["restore", "--backup", str(backup), "--yes", "--data-dir", str(data_dir)]) == 0
