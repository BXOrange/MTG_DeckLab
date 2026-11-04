"""PLR-16: legacy player-asset rows -> account ownership, on temporary copies only."""

import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

from mtg_analyzer.services.account_store import AccountStore
from mtg_analyzer.services.player_assets import PlayerAssetStore

_SPEC = importlib.util.spec_from_file_location(
    "migrate_legacy_decks_assets", Path(__file__).resolve().parent.parent / "scripts" / "migrate_legacy_decks.py"
)
mig = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = mig
_SPEC.loader.exec_module(mig)

LEGACY_SCHEMA = """
CREATE TABLE token_images (player_name TEXT NOT NULL, token_name TEXT NOT NULL, content_type TEXT NOT NULL,
    data BLOB NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY (player_name, token_name));
CREATE TABLE sleeves (player_name TEXT NOT NULL, sleeve_id TEXT NOT NULL, label TEXT NOT NULL,
    content_type TEXT NOT NULL, data BLOB NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY (player_name, sleeve_id));
CREATE TABLE favorite_decks (player_name TEXT NOT NULL, deck_id TEXT NOT NULL, updated_at TEXT NOT NULL,
    PRIMARY KEY (player_name, deck_id));
"""


@pytest.fixture
def data_dir(tmp_path):
    path = tmp_path / "data"
    path.mkdir()
    conn = sqlite3.connect(path / "player_assets.db")
    conn.executescript(LEGACY_SCHEMA)
    conn.executescript(
        """
        INSERT INTO sleeves VALUES ('Bernd', 's1', 'Mine', 'image/png', x'89504e47', '2024-01-01');
        INSERT INTO sleeves VALUES ('stranger', 's2', 'Theirs', 'image/png', x'89504e48', '2024-01-02');
        INSERT INTO token_images VALUES ('Bernd', 'Soldier', 'image/png', x'0102', '2024-01-03');
        INSERT INTO favorite_decks VALUES ('bernd', 'deck-1', '2024-01-04');
        """
    )
    conn.commit()
    conn.close()
    accounts = AccountStore(path / "accounts.db")
    accounts.create_account_unchecked("Bernd", "!", "player")
    accounts.close()
    return path


def _uuid(data_dir, name="Bernd"):
    store = AccountStore(data_dir / "accounts.db")
    try:
        return store.get_by_name(name).player_uuid
    finally:
        store.close()


def _owners(data_dir):
    conn = sqlite3.connect(data_dir / "player_assets.db")
    try:
        rows = {}
        for table in ("token_images", "sleeves", "favorite_decks"):
            for legacy, owner in conn.execute(f"SELECT legacy_name, owner_uuid FROM {table}"):
                rows.setdefault(legacy, set()).add(owner)
        return rows
    finally:
        conn.close()


def test_default_assigns_nothing_and_lists_every_name(data_dir):
    report = mig.apply(data_dir)
    assert _owners(data_dir) == {"Bernd": {None}, "stranger": {None}, "bernd": {None}}
    text = report.text()
    assert "UNASSIGNED" in text and "'stranger'" in text
    assert "rerun with --assign-assets-by-name" in text  # Bernd matches an account but policy is off
    with PlayerAssetStore(data_dir / "player_assets.db") as store:
        assert store.list_sleeves(_uuid(data_dir)) == []  # invisible to the runtime


def test_preview_is_read_only_and_reports_the_plan(data_dir):
    before = (data_dir / "player_assets.db").read_bytes()
    report = mig.preview(data_dir, assign_assets_by_name=True)
    assert (data_dir / "player_assets.db").read_bytes() == before
    assert not (data_dir / "migration").exists()
    plan = report.plans["assets"]
    assert plan.assign == {"Bernd": _uuid(data_dir), "bernd": _uuid(data_dir)}
    assert plan.unassigned == {"stranger": 1}


def test_assign_by_name_matches_only_unique_normalized_names(data_dir):
    report = mig.apply(data_dir, assign_assets_by_name=True)
    me = _uuid(data_dir)
    assert _owners(data_dir) == {"Bernd": {me}, "bernd": {me}, "stranger": {None}}
    with PlayerAssetStore(data_dir / "player_assets.db") as store:
        assert [s["sleeve_id"] for s in store.list_sleeves(me)] == ["s1"]
        assert store.get_sleeve(me, "s2") is None
        assert store.list_favorite_decks(me) == ["deck-1"]
        assert [t["token_name"] for t in store.list_token_images(me)] == ["Soldier"]
        assert store.schema_version == 1
    assert report.applied and "ASSIGN" in report.text()


def test_repeat_run_changes_nothing(data_dir):
    mig.apply(data_dir, assign_assets_by_name=True)
    snapshot = (data_dir / "player_assets.db").read_bytes()
    report = mig.apply(data_dir, assign_assets_by_name=True)
    assert report.applied
    assert (data_dir / "player_assets.db").read_bytes() == snapshot


def test_switching_the_policy_on_a_resumed_run_is_refused(data_dir):
    mig.apply(data_dir)
    with pytest.raises(mig.MigrationError, match="assign_assets_by_name"):
        mig.apply(data_dir, assign_assets_by_name=True)


def test_crash_after_workcopy_resumes_to_the_same_result(data_dir):
    def crash(store, step):
        if (store, step) == ("assets", "workcopy"):
            raise RuntimeError("power cut")

    with pytest.raises(RuntimeError):
        mig.apply(data_dir, assign_assets_by_name=True, after_step=crash)
    assert "legacy_name" not in {r[1] for r in sqlite3.connect(data_dir / "player_assets.db").execute("PRAGMA table_info(sleeves)")}
    mig.apply(data_dir, assign_assets_by_name=True)
    assert _owners(data_dir)["Bernd"] == {_uuid(data_dir)}


def test_crash_after_live_commit_before_journal_is_idempotent(data_dir, monkeypatch):
    real_verify = mig._verify_assets
    calls = []

    def flaky(path, digest, assign):
        calls.append(path)
        if len(calls) == 2:  # the live verification
            raise RuntimeError("crash before the journal mark")
        return real_verify(path, digest, assign)

    monkeypatch.setattr(mig, "_verify_assets", flaky)
    with pytest.raises(RuntimeError):
        mig.apply(data_dir, assign_assets_by_name=True)
    monkeypatch.setattr(mig, "_verify_assets", real_verify)
    mig.apply(data_dir, assign_assets_by_name=True)
    assert _owners(data_dir)["Bernd"] == {_uuid(data_dir)}


def test_content_is_byte_identical_and_restorable(data_dir):
    before = sqlite3.connect(data_dir / "player_assets.db").execute("SELECT * FROM sleeves ORDER BY sleeve_id").fetchall()
    report = mig.apply(data_dir, assign_assets_by_name=True)
    after = sqlite3.connect(data_dir / "player_assets.db").execute(
        "SELECT legacy_name, sleeve_id, label, content_type, data, updated_at FROM sleeves ORDER BY sleeve_id"
    ).fetchall()
    assert after == before
    mig.restore(data_dir, report.backup_dir)
    assert sqlite3.connect(data_dir / "player_assets.db").execute("SELECT * FROM sleeves ORDER BY sleeve_id").fetchall() == before


def test_admin_account_never_receives_assets(data_dir):
    accounts = AccountStore(data_dir / "accounts.db")
    accounts.create_account_unchecked("stranger", "!", "admin")
    accounts.close()
    mig.apply(data_dir, assign_assets_by_name=True)
    assert _owners(data_dir)["stranger"] == {None}


def test_key_conflict_with_an_existing_owned_row_is_left_unassigned_and_reported(data_dir):
    me = _uuid(data_dir)
    with PlayerAssetStore(data_dir / "player_assets.db") as store:  # already migrated shape + a new owned row
        store.save_token_image(me, "Soldier", "image/png", b"new")
    report = mig.apply(data_dir, assign_assets_by_name=True)
    conn = sqlite3.connect(data_dir / "player_assets.db")
    kept = conn.execute("SELECT data FROM token_images WHERE owner_uuid = ?", (me,)).fetchall()
    assert kept == [(b"new",)]  # never overwritten
    assert conn.execute("SELECT COUNT(*) FROM token_images WHERE owner_uuid IS NULL").fetchone()[0] == 1
    assert "LEFT UNASSIGNED" in report.text()


def test_missing_accounts_db_assigns_nothing(data_dir):
    (data_dir / "accounts.db").unlink()
    mig.apply(data_dir, assign_assets_by_name=True)
    assert set().union(*_owners(data_dir).values()) == {None}
