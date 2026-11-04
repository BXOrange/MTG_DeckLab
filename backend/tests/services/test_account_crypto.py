"""PLR-9e: `accounts.db` is encrypted at rest; key handling, conversion, rekey, backup and restore.

All on temporary directories with throwaway keys. Never touches `MTG_DATA_DIR`.
"""

import os
import stat
import sys
from pathlib import Path

import pytest
from sqlcipher3 import dbapi2 as sqlcipher

from mtg_analyzer import config
from mtg_analyzer.services import account_crypto as crypto
from mtg_analyzer.services.account_store import AccountStore
from mtg_analyzer.services.password_hasher import PasswordHasher
from mtg_analyzer.services import totp

NAME = "Zarathustra"
HASH = PasswordHasher(n=2 ** 4).hash("correct horse battery")


@pytest.fixture
def paths(tmp_path, monkeypatch):
    data = tmp_path / "data"
    keys = tmp_path / "keys"
    data.mkdir()
    monkeypatch.setattr(config, "DATA_DIR", data)
    monkeypatch.setattr(config, "ACCOUNTS_DB_KEY_FILE", keys / "accounts.key")
    return data / "accounts.db", keys / "accounts.key"


def _populate(db_path: Path, key: bytes | None, secret: str = "JBSWY3DPEHPK3PXP") -> None:
    store = AccountStore(db_path, key=key)
    admin = store.create_account_unchecked(NAME, HASH, "admin")
    store.begin_mfa_enrollment(admin.player_uuid, secret)
    store.record_audit(NAME, "test.event")
    store.close()


def _raw_bytes(db_path: Path) -> bytes:
    blob = b""
    for suffix in ("", "-wal", "-shm"):
        sibling = db_path.with_name(db_path.name + suffix)
        if sibling.exists():
            blob += sibling.read_bytes()
    return blob


def test_encrypted_file_has_no_plaintext_even_with_wal(paths):
    db_path, _ = paths
    key = crypto.new_key()
    store = AccountStore(db_path, key=key)  # left open: pending pages live in the WAL
    admin = store.create_account_unchecked(NAME, HASH, "admin")
    store.begin_mfa_enrollment(admin.player_uuid, "JBSWY3DPEHPK3PXP")
    raw = _raw_bytes(db_path)
    assert db_path.with_name("accounts.db-wal").exists()
    for needle in (NAME.encode(), HASH.encode(), b"JBSWY3DPEHPK3PXP", b"SQLite format 3", b"audit_log"):
        assert needle not in raw
    store.close()
    assert not crypto.looks_plaintext(db_path)
    assert b"JBSWY3DPEHPK3PXP" not in _raw_bytes(db_path)


def test_reopen_with_right_key_reads_data(paths):
    db_path, _ = paths
    key = crypto.new_key()
    _populate(db_path, key)
    reopened = AccountStore(db_path, key=key)
    assert reopened.get_by_name(NAME).name == NAME
    assert reopened.pending_mfa_secret(reopened.get_by_name(NAME).player_uuid) == "JBSWY3DPEHPK3PXP"
    reopened.close()


def test_wrong_key_is_refused_and_file_untouched(paths):
    db_path, _ = paths
    _populate(db_path, crypto.new_key())
    before = db_path.read_bytes()
    with pytest.raises(crypto.AccountKeyRejectedError):
        AccountStore(db_path, key=crypto.new_key())
    with pytest.raises(crypto.AccountKeyRejectedError):
        AccountStore(db_path, key=None)  # no key at all is not "plaintext mode"
    assert db_path.read_bytes() == before


def test_plaintext_file_under_a_key_is_refused_not_overwritten(paths):
    db_path, _ = paths
    _populate(db_path, None)
    assert crypto.looks_plaintext(db_path)
    before = db_path.read_bytes()
    with pytest.raises(crypto.AccountDbPlaintextError):
        AccountStore(db_path, key=crypto.new_key())
    assert db_path.read_bytes() == before


def test_missing_key_refuses_when_database_exists(paths):
    db_path, key_file = paths
    _populate(db_path, crypto.new_key())
    with pytest.raises(crypto.AccountKeyMissingError) as info:
        crypto.resolve_key(db_path, allow_create=True)  # even allow_create must not mint a key for an existing db
    assert "encrypt-db" in str(info.value)
    assert not key_file.exists()


def test_missing_key_without_create_refuses(paths):
    db_path, key_file = paths
    with pytest.raises(crypto.AccountKeyMissingError):
        crypto.resolve_key(db_path)
    assert not key_file.exists() and not db_path.exists()


def test_fresh_install_generates_a_private_key_outside_the_data_dir(paths):
    db_path, key_file = paths
    key = crypto.resolve_key(db_path, allow_create=True)
    assert len(key) == crypto.KEY_BYTES and key_file.exists()
    assert crypto.parse_key(key_file.read_text()) == key
    assert crypto.resolve_key(db_path) == key  # now found
    if sys.platform != "win32":
        assert stat.S_IMODE(key_file.stat().st_mode) == crypto.PRIVATE_FILE_MODE
        assert stat.S_IMODE(key_file.parent.stat().st_mode) == crypto.PRIVATE_DIR_MODE


def test_env_key_wins_over_key_file(paths, monkeypatch):
    db_path, key_file = paths
    crypto.write_key_file(key_file, crypto.new_key())
    env_key = crypto.new_key()
    monkeypatch.setenv(config.ACCOUNTS_DB_KEY_ENV, env_key.hex())
    assert crypto.resolve_key(db_path) == env_key
    assert crypto.key_source() == "env"


@pytest.mark.parametrize("text", ["", "abc", "zz" * 32, "ab" * 31, "ab" * 33])
def test_malformed_key_is_rejected(text):
    with pytest.raises(crypto.AccountKeyInvalidError):
        crypto.parse_key(text)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX modes")
def test_key_file_readable_by_others_is_refused(paths):
    db_path, key_file = paths
    crypto.write_key_file(key_file, crypto.new_key())
    os.chmod(key_file, 0o644)
    with pytest.raises(crypto.AccountKeyInvalidError, match="readable by other"):
        crypto.resolve_key(db_path)


def test_key_file_inside_data_dir_is_refused(paths, monkeypatch):
    db_path, _ = paths
    inside = db_path.parent / "accounts.key"
    monkeypatch.setattr(config, "ACCOUNTS_DB_KEY_FILE", inside)
    with pytest.raises(crypto.AccountKeyInvalidError, match="inside the data directory"):
        crypto.write_key_file(inside, crypto.new_key())


def test_write_key_file_never_overwrites(paths):
    _, key_file = paths
    crypto.write_key_file(key_file, crypto.new_key())
    with pytest.raises(FileExistsError):
        crypto.write_key_file(key_file, crypto.new_key())


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX modes")
def test_database_and_sidecars_are_owner_only(paths):
    db_path, _ = paths
    store = AccountStore(db_path, key=crypto.new_key())
    store.create_account_unchecked(NAME, HASH, "player")
    for suffix in ("", "-wal", "-shm"):
        sibling = db_path.with_name(db_path.name + suffix)
        assert sibling.exists()
        assert stat.S_IMODE(sibling.stat().st_mode) == crypto.PRIVATE_FILE_MODE
    store.close()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX modes")
def test_harden_data_dir_locks_directory_and_stores(tmp_path):
    data = tmp_path / "data"
    (data / "migration" / "backup-1").mkdir(parents=True)
    (data / "migration" / "backup-1" / "decks.db").write_bytes(b"x")
    for name in ("decks.db", "decks.db-wal", "mcp_server_token", "other.txt"):
        (data / name).write_bytes(b"x")
        os.chmod(data / name, 0o644)
    crypto.harden_data_dir(data)
    mode = lambda p: stat.S_IMODE(p.stat().st_mode)  # noqa: E731
    assert mode(data) == crypto.PRIVATE_DIR_MODE
    assert mode(data / "decks.db") == mode(data / "decks.db-wal") == mode(data / "mcp_server_token") == 0o600
    assert mode(data / "migration" / "backup-1") == 0o700
    assert mode(data / "migration" / "backup-1" / "decks.db") == 0o600
    assert mode(data / "other.txt") == 0o644  # unknown files are not ours to change


def test_convert_plaintext_to_encrypted_verifies_and_swaps(paths):
    db_path, _ = paths
    _populate(db_path, None)
    assert crypto.looks_plaintext(db_path)
    key = crypto.new_key()
    counts = crypto.encrypt_plaintext_database(db_path, key)
    assert counts["accounts"] == 1
    assert not crypto.looks_plaintext(db_path)
    assert NAME.encode() not in _raw_bytes(db_path)
    assert not list(db_path.parent.glob("*.tmp")) and not db_path.with_name("accounts.db-wal").exists()
    store = AccountStore(db_path, key=key)
    assert store.get_by_name(NAME) is not None
    assert store.schema_version >= 3
    store.close()


def test_convert_keeps_plaintext_only_where_the_operator_says(paths, tmp_path):
    db_path, _ = paths
    _populate(db_path, None)
    kept = tmp_path / "plain-backup" / "accounts.plain.db"
    crypto.encrypt_plaintext_database(db_path, crypto.new_key(), keep_plaintext_backup=kept)
    assert crypto.looks_plaintext(kept) and not crypto.looks_plaintext(db_path)


def test_convert_refuses_an_encrypted_file(paths):
    db_path, _ = paths
    _populate(db_path, crypto.new_key())
    with pytest.raises(crypto.AccountDbError, match="not a plaintext"):
        crypto.encrypt_plaintext_database(db_path, crypto.new_key())


def test_failed_verification_leaves_the_original(paths, monkeypatch):
    db_path, _ = paths
    _populate(db_path, None)
    before = db_path.read_bytes()

    def boom(*args, **kwargs):
        raise crypto.AccountDbError("verification failed")

    monkeypatch.setattr(crypto, "verify_copy", boom)
    with pytest.raises(crypto.AccountDbError):
        crypto.encrypt_plaintext_database(db_path, crypto.new_key())
    assert db_path.read_bytes() == before
    assert not list(db_path.parent.glob("*.tmp"))


def test_rekey_changes_the_key(paths):
    db_path, _ = paths
    old, new = crypto.new_key(), crypto.new_key()
    _populate(db_path, old)
    crypto.rekey_database(db_path, old, new)
    with pytest.raises(crypto.AccountKeyRejectedError):
        AccountStore(db_path, key=old)
    store = AccountStore(db_path, key=new)
    assert store.get_by_name(NAME) is not None
    store.close()


def test_backup_is_encrypted_consistent_and_never_overwritten(paths, tmp_path):
    db_path, _ = paths
    key = crypto.new_key()
    live = AccountStore(db_path, key=key)  # the server keeps running during a backup
    live.create_account_unchecked(NAME, HASH, "admin")
    target = tmp_path / "backups" / "copy.db"
    counts = crypto.backup_database(db_path, key, target)
    assert counts["accounts"] == 1
    assert NAME.encode() not in target.read_bytes() and not crypto.looks_plaintext(target)
    with pytest.raises(crypto.AccountDbError, match="already exists"):
        crypto.backup_database(db_path, key, target)
    live.close()


def test_restore_replaces_and_keeps_previous_file(paths, tmp_path):
    db_path, _ = paths
    key = crypto.new_key()
    store = AccountStore(db_path, key=key)
    store.create_account_unchecked(NAME, HASH, "admin")
    store.close()
    backup = tmp_path / "b.db"
    crypto.backup_database(db_path, key, backup)
    store = AccountStore(db_path, key=key)
    store.create_account_unchecked("Another", HASH, "player")
    store.close()
    preserved = crypto.restore_database(backup, key, db_path)
    restored = AccountStore(db_path, key=key)
    assert restored.get_by_name("Another") is None and restored.get_by_name(NAME) is not None
    restored.close()
    kept = AccountStore(preserved, key=key)
    assert kept.get_by_name("Another") is not None
    kept.close()


def test_restore_refuses_a_backup_under_another_key(paths, tmp_path):
    db_path, _ = paths
    key = crypto.new_key()
    _populate(db_path, key)
    backup = tmp_path / "b.db"
    crypto.backup_database(db_path, key, backup)
    before = db_path.read_bytes()
    with pytest.raises(crypto.AccountKeyRejectedError):
        crypto.restore_database(backup, crypto.new_key(), db_path)
    assert db_path.read_bytes() == before


def test_purge_expired_removes_only_dead_rows(paths):
    db_path, _ = paths
    clock = [1_000_000.0]
    store = AccountStore(db_path, key=crypto.new_key(), clock=lambda: clock[0])
    account = store.create_account_unchecked(NAME, HASH, "player")
    store.create_session(account.player_uuid)
    dead_token, _ = store.create_session(account.player_uuid)
    store.revoke_session(dead_token)
    store.record_audit("x", "old.event")
    assert not any(store.purge_expired().values())  # nothing is old yet
    clock[0] += config.SESSION_RETENTION_SECONDS + 1
    purged = store.purge_expired()
    assert purged["sessions"] >= 1 and purged["audit_log"] == 0  # sessions go first, the audit log stays
    assert store.get(account.player_uuid) is not None
    clock[0] += config.AUDIT_RETENTION_SECONDS
    assert store.purge_expired()["audit_log"] == 1
    store.close()


def test_totp_secret_helper_still_works_encrypted(paths):
    db_path, _ = paths
    store = AccountStore(db_path, key=crypto.new_key())
    admin = store.create_account_unchecked(NAME, HASH, "admin")
    secret = totp.new_secret()
    store.begin_mfa_enrollment(admin.player_uuid, secret)
    assert store.pending_mfa_secret(admin.player_uuid) == secret
    assert secret.encode() not in _raw_bytes(db_path)
    store.close()
    _ = sqlcipher  # the binding is what the store runs on
