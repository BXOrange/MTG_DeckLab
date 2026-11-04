"""PLR-9e: operator commands for the encrypted `accounts.db` (init-key, encrypt-db, rekey, backup, restore, status)."""

import importlib.util
import sys
from pathlib import Path

import pytest

from mtg_analyzer import config
from mtg_analyzer.services import account_crypto as crypto
from mtg_analyzer.services.account_store import AccountStore
from mtg_analyzer.services.password_hasher import PasswordHasher

_SPEC = importlib.util.spec_from_file_location(
    "manage_accounts_crypto", Path(__file__).resolve().parent.parent / "scripts" / "manage_accounts.py"
)
manage = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(manage)

HASH = PasswordHasher(n=2 ** 4).hash("correct horse battery")


@pytest.fixture
def env(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(config, "DATA_DIR", data)
    monkeypatch.setattr(config, "ACCOUNTS_DB_PATH", data / "accounts.db")
    monkeypatch.setattr(config, "ACCOUNTS_DB_KEY_FILE", tmp_path / "keys" / "accounts.key")
    monkeypatch.setattr(config, "ACCOUNTS_BACKUP_DIR", tmp_path / "backups")
    return config.ACCOUNTS_DB_PATH, config.ACCOUNTS_DB_KEY_FILE


def _legacy_plaintext(path: Path) -> None:
    store = AccountStore(path)  # no key: how the pre-cutover install wrote it
    store.create_account_unchecked("LegacyAdmin", HASH, "admin")
    store.close()


def test_encrypt_db_needs_confirmation_and_changes_nothing_without_it(env, capsys):
    db, _ = env
    _legacy_plaintext(db)
    before = db.read_bytes()
    assert manage.main(["encrypt-db"]) == 1
    assert db.read_bytes() == before and "--yes" in capsys.readouterr().err


def test_encrypt_db_converts_with_a_new_key_file(env, capsys):
    db, key_file = env
    _legacy_plaintext(db)
    assert manage.main(["encrypt-db", "--yes"]) == 0
    assert key_file.exists() and not crypto.looks_plaintext(db)
    store = AccountStore(db, key=crypto.configured_key())
    assert store.get_by_name("LegacyAdmin") is not None
    store.close()
    assert "plaintext original was removed" in capsys.readouterr().out
    assert manage.main(["encrypt-db", "--yes"]) == 1  # already encrypted: refuses


def test_encrypt_db_keep_plaintext_warns_loudly(env, tmp_path, capsys):
    db, _ = env
    _legacy_plaintext(db)
    kept = tmp_path / "keep" / "plain.db"
    assert manage.main(["encrypt-db", "--yes", "--keep-plaintext-backup", str(kept)]) == 0
    assert crypto.looks_plaintext(kept) and "WARNING" in capsys.readouterr().out


def test_commands_refuse_without_a_key_for_an_existing_database(env, capsys):
    db, key_file = env
    store = AccountStore(db, key=crypto.new_key())  # encrypted under a key nobody configured
    store.close()
    assert manage.main(["list"]) == 1
    assert "no key is configured" in capsys.readouterr().err
    assert not key_file.exists()


def test_fresh_install_invite_creates_key_and_encrypted_db(env, capsys):
    db, key_file = env
    assert manage.main(["invite"]) == 0
    assert key_file.exists() and db.exists() and not crypto.looks_plaintext(db)


def test_init_key_never_replaces(env, capsys):
    _, key_file = env
    assert manage.main(["init-key"]) == 0
    first = key_file.read_text()
    assert manage.main(["init-key"]) == 1
    assert key_file.read_text() == first


def test_rekey_swaps_key_file_and_keeps_the_old_one(env, capsys):
    db, key_file = env
    manage.main(["init-key"])
    store = AccountStore(db, key=crypto.configured_key())
    store.create_account_unchecked("Someone", HASH, "player")
    store.close()
    old = key_file.read_text()
    assert manage.main(["rekey"]) == 1  # needs --yes
    assert manage.main(["rekey", "--yes"]) == 0
    assert key_file.read_text() != old
    previous = list(key_file.parent.glob("accounts.key.previous-*"))
    assert len(previous) == 1 and previous[0].read_text() == old
    store = AccountStore(db, key=crypto.configured_key())
    assert store.get_by_name("Someone") is not None
    store.close()


def test_backup_and_restore_round_trip_with_pruning(env, tmp_path, capsys):
    db, _ = env
    manage.main(["init-key"])
    store = AccountStore(db, key=crypto.configured_key())
    store.create_account_unchecked("Keep", HASH, "player")
    store.close()
    backups = Path(config.ACCOUNTS_BACKUP_DIR)
    backups.mkdir(parents=True)
    for index in range(3):  # three stale managed backups
        (backups / f"accounts-2020010{index}T000000Z.db").write_bytes(b"old")
    assert manage.main(["backup", "--keep", "2"]) == 0
    remaining = sorted(p.name for p in backups.glob("accounts-*.db"))
    assert len(remaining) == 2 and remaining[-1] > "accounts-2025"  # the new one survives pruning
    newest = backups / remaining[-1]
    assert b"Keep" not in newest.read_bytes()
    store = AccountStore(db, key=crypto.configured_key())
    store.create_account_unchecked("Later", HASH, "player")
    store.close()
    assert manage.main(["restore", str(newest)]) == 1  # needs --yes
    assert manage.main(["restore", str(newest), "--yes"]) == 0
    store = AccountStore(db, key=crypto.configured_key())
    assert store.get_by_name("Later") is None and store.get_by_name("Keep") is not None
    store.close()


def test_status_reports_each_state(env, capsys):
    db, _ = env
    assert manage.main(["status"]) == 1  # no db, no key
    _legacy_plaintext(db)
    assert manage.main(["status"]) == 1 and "plaintext" in capsys.readouterr().out
    manage.main(["encrypt-db", "--yes"])
    capsys.readouterr()
    assert manage.main(["status"]) == 0 and "opens:     yes" in capsys.readouterr().out
