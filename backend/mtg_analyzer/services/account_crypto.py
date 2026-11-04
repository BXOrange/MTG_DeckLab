"""Encryption at rest for `accounts.db` and the file permissions around it (PLR-9e, plan section 7).

`accounts.db` holds password hashes, session digests, invitation digests, the audit log and the
admin TOTP secrets, so it is the one store encrypted with SQLCipher (AES-256, a page-level cipher
that also covers the WAL, journals and temp files). The other stores rely on an encrypted volume.

Key handling (decision recorded in the plan, section 7):

* The key is 32 random bytes, written as 64 hex characters. It is passed to SQLCipher as a raw key
  (`x'<hex>'`), which skips the passphrase KDF: it is already high-entropy.
* It lives **outside** the database, the data directory and every backup: first the
  `MTG_ACCOUNTS_DB_KEY` environment variable, else a key file (`MTG_ACCOUNTS_DB_KEY_FILE`, default
  `~/.decklab/accounts.key`) that must be mode 0600 on POSIX systems. An OS secret store (macOS
  Keychain, Windows Credential Manager) is deliberately *not* used: it needs a platform-specific
  dependency and does not exist on a headless server.
* A missing or wrong key **refuses to start**; there is no fallback to plaintext and no fresh empty
  database is ever created over an existing file. A key file is only generated, with a loud log
  line, when neither a key nor a database exists yet (a brand-new install).

Everything here is stdlib plus the `sqlcipher3` binding.
"""

from __future__ import annotations

import logging
import os
import re
import secrets
import stat
import sys
import tempfile
from pathlib import Path
from typing import Optional

from sqlcipher3 import dbapi2 as sqlcipher

from mtg_analyzer import config

logger = logging.getLogger(__name__)

#: Bytes of entropy in the database key (256 bits, SQLCipher's AES-256 key size).
KEY_BYTES = 32
KEY_HEX_LENGTH = KEY_BYTES * 2
_KEY_PATTERN = re.compile(rf"[0-9a-fA-F]{{{KEY_HEX_LENGTH}}}")

#: First bytes of an unencrypted SQLite file; an encrypted one starts with random bytes.
PLAIN_SQLITE_HEADER = b"SQLite format 3\x00"

#: Permission bits for private files and directories (owner only), where the platform has them.
PRIVATE_FILE_MODE = 0o600
PRIVATE_DIR_MODE = 0o700
_GROUP_OTHER_BITS = stat.S_IRWXG | stat.S_IRWXO

#: SQLite sidecar files that sit next to a database and hold page data (journal/WAL/shared memory).
SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")

#: Names (substrings) of the data-directory files `harden_data_dir` locks down.
_DB_SUFFIXES = (".db", ".json", ".log")
#: Other secret-bearing files that live directly in the data directory.
_PRIVATE_NAMES = ("mcp_server_token",)


class AccountDbError(RuntimeError):
    """The account database cannot be opened safely; the message tells the operator what to do."""

    code = "account_db_error"


class AccountKeyMissingError(AccountDbError):
    code = "account_key_missing"


class AccountKeyInvalidError(AccountDbError):
    code = "account_key_invalid"


class AccountKeyRejectedError(AccountDbError):
    """The key does not open the file (wrong key, or the file is not a database)."""

    code = "account_key_rejected"


class AccountDbPlaintextError(AccountDbError):
    """A legacy unencrypted `accounts.db` was found; it must be converted explicitly."""

    code = "account_db_plaintext"


# -- keys --------------------------------------------------------------------


def parse_key(text: str) -> bytes:
    """A key from its 64-hex-character text form (surrounding whitespace ignored)."""
    cleaned = text.strip()
    if not _KEY_PATTERN.fullmatch(cleaned):
        raise AccountKeyInvalidError(
            f"The accounts database key must be {KEY_HEX_LENGTH} hexadecimal characters "
            f"({KEY_BYTES} random bytes). Create one with: scripts/manage_accounts.py init-key"
        )
    return bytes.fromhex(cleaned)


def new_key() -> bytes:
    return secrets.token_bytes(KEY_BYTES)


def _is_inside(path: Path, directory: Path) -> bool:
    try:
        path.resolve().relative_to(directory.resolve())
        return True
    except ValueError:
        return False


def check_key_file(path: Path) -> None:
    """Refuse a key file that is not a private regular file outside the data directory."""
    if _is_inside(path, config.DATA_DIR):
        raise AccountKeyInvalidError(
            f"The key file {path} lies inside the data directory {config.DATA_DIR}; a copy of the "
            "data directory would carry its own key. Move it elsewhere (MTG_ACCOUNTS_DB_KEY_FILE)."
        )
    info = path.stat()
    if not stat.S_ISREG(info.st_mode):
        raise AccountKeyInvalidError(f"The key file {path} is not a regular file.")
    if sys.platform != "win32" and info.st_mode & _GROUP_OTHER_BITS:
        raise AccountKeyInvalidError(
            f"The key file {path} is readable by other users (mode {stat.S_IMODE(info.st_mode):o}). "
            f"Run: chmod {PRIVATE_FILE_MODE:o} {path}"
        )


def write_key_file(path: Path, key: bytes, *, overwrite: bool = False) -> None:
    """Create the key file owner-only (0600, parent 0700 when created); never replaces silently."""
    path = Path(path)
    if _is_inside(path, config.DATA_DIR):
        raise AccountKeyInvalidError(f"Refusing to store the key inside the data directory ({path}).")
    created_parent = not path.parent.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    if created_parent:
        restrict(path.parent, directory=True)
    flags = os.O_WRONLY | os.O_CREAT | (os.O_TRUNC if overwrite else os.O_EXCL)
    fd = os.open(path, flags, PRIVATE_FILE_MODE)
    with os.fdopen(fd, "w") as handle:
        handle.write(key.hex() + "\n")
    restrict(path)


def configured_key() -> Optional[bytes]:
    """The key from the environment or the key file, or None when neither exists."""
    raw = os.environ.get(config.ACCOUNTS_DB_KEY_ENV)
    if raw:
        return parse_key(raw)
    path = Path(config.ACCOUNTS_DB_KEY_FILE)
    if path.exists():
        check_key_file(path)
        return parse_key(path.read_text())
    return None


def key_source() -> Optional[str]:
    """Where the configured key comes from: "env", "file" or None (for `status` and `rekey`)."""
    if os.environ.get(config.ACCOUNTS_DB_KEY_ENV):
        return "env"
    return "file" if Path(config.ACCOUNTS_DB_KEY_FILE).exists() else None


def resolve_key(db_path: Path | str, *, allow_create: bool = False) -> bytes:
    """The key to open `db_path` with, for the running server or an operator command.

    A missing key stops here with instructions. Only when `allow_create` is set, no key is
    configured **and** no database file exists is a key file generated (fresh install)."""
    key = configured_key()
    if key is not None:
        return key
    db_path = Path(db_path)
    key_file = Path(config.ACCOUNTS_DB_KEY_FILE)
    if allow_create and not db_path.exists():
        key = new_key()
        write_key_file(key_file, key)
        logger.warning(
            "NEW ACCOUNTS DATABASE KEY written to %s (mode 600). Back this file up somewhere other than "
            "the data directory: without it the encrypted accounts.db cannot be opened.", key_file,
        )
        return key
    if db_path.exists():
        problem = (
            f"{db_path} exists but no key is configured. Set {config.ACCOUNTS_DB_KEY_ENV} or put the key in "
            f"{key_file}. A legacy plaintext accounts.db is converted with: "
            "scripts/manage_accounts.py encrypt-db"
        )
    else:
        problem = (
            f"No accounts database key is configured. Create one with: scripts/manage_accounts.py init-key "
            f"(writes {key_file}), or set {config.ACCOUNTS_DB_KEY_ENV}."
        )
    raise AccountKeyMissingError(problem)


# -- opening ------------------------------------------------------------------


def key_pragma(key: bytes, name: str = "key") -> str:
    """`PRAGMA key = "x'<hex>'"`; the hex form cannot carry SQL."""
    return f"PRAGMA {name} = \"x'{key.hex()}'\""


def looks_plaintext(path: Path | str) -> bool:
    """Whether `path` is an existing unencrypted SQLite file."""
    try:
        with open(path, "rb") as handle:
            return handle.read(len(PLAIN_SQLITE_HEADER)) == PLAIN_SQLITE_HEADER
    except OSError:
        return False


def apply_key(conn, key: Optional[bytes]) -> None:
    if key is not None:
        conn.execute(key_pragma(key))


def verify_open(conn) -> None:
    """Read the schema: this is the first statement that fails on a wrong key."""
    conn.execute("SELECT count(*) FROM sqlite_master").fetchone()


def open_connection(path: Path | str, key: Optional[bytes], **kwargs):
    """A SQLCipher connection keyed and verified, or a clear `AccountDbError`.

    `key=None` opens the file without a key; that is for unit tests with `:memory:` and for
    reading a legacy plaintext file during conversion, never for the server (see `resolve_key`)."""
    target = str(path)
    on_disk = target != ":memory:" and Path(target).exists()
    if key is not None and on_disk and looks_plaintext(target):
        raise AccountDbPlaintextError(
            f"{target} is an unencrypted legacy database. Convert it first (stop the server, then): "
            "scripts/manage_accounts.py encrypt-db"
        )
    conn = sqlcipher.connect(target, **kwargs)
    try:
        apply_key(conn, key)
        verify_open(conn)
    except sqlcipher.DatabaseError as exc:
        conn.close()
        raise AccountKeyRejectedError(
            f"{target} could not be opened with the configured key ({exc}). Wrong or lost key, "
            "or the file is damaged. Nothing was changed; restore the key or an encrypted backup."
        ) from exc
    return conn


# -- permissions --------------------------------------------------------------


def restrict(path: Path | str, *, directory: bool = False) -> None:
    """Owner-only mode (0600 file / 0700 directory). A no-op on Windows, which has no POSIX modes:
    there the profile directory's inherited ACL is what protects it (SERVER_GUIDE section 4)."""
    if sys.platform == "win32":
        return
    try:
        os.chmod(path, PRIVATE_DIR_MODE if directory else PRIVATE_FILE_MODE)
    except OSError:
        logger.warning("could not restrict permissions of %s", path)


def restrict_database_files(db_path: Path | str) -> None:
    """Lock down a database file and its journal/WAL/shared-memory siblings."""
    db_path = Path(db_path)
    for candidate in [db_path, *(db_path.with_name(db_path.name + suffix) for suffix in SIDECAR_SUFFIXES)]:
        if candidate.exists():
            restrict(candidate)


def harden_data_dir(data_dir: Path | str) -> None:
    """Owner-only data directory, databases, sidecars, logs and migration backups (plan section 7)."""
    data_dir = Path(data_dir)
    if not data_dir.is_dir():
        return
    restrict(data_dir, directory=True)
    for child in data_dir.iterdir():
        if child.is_dir() and child.name in ("backups", "logs", "migration"):
            restrict(child, directory=True)
            for inner in child.rglob("*"):
                restrict(inner, directory=inner.is_dir())
        elif child.is_file() and (
            child.suffix in _DB_SUFFIXES or child.name.endswith(SIDECAR_SUFFIXES) or child.name in _PRIVATE_NAMES
        ):
            restrict(child)


def private_temp_path(directory: Path, name: str) -> Path:
    """A fresh not-yet-existing sibling path for atomic writes (same filesystem, so rename is atomic)."""
    fd, raw = tempfile.mkstemp(prefix=f".{name}.", suffix=".tmp", dir=directory)
    os.close(fd)
    os.unlink(raw)
    return Path(raw)


# -- operator operations ------------------------------------------------------


def _checkpoint(conn) -> None:
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()


def _export(src, target_path: Path, target_key: Optional[bytes]) -> None:
    """Copy every table of an open connection into a new database with `sqlcipher_export`."""
    version = src.execute("PRAGMA user_version").fetchone()[0]
    key_clause = f"\"x'{target_key.hex()}'\"" if target_key is not None else "''"
    src.execute(f"ATTACH DATABASE ? AS target KEY {key_clause}", (str(target_path),))
    try:
        src.execute("SELECT sqlcipher_export('target')").fetchall()
        src.execute(f"PRAGMA target.user_version = {int(version)}")
    finally:
        src.execute("DETACH DATABASE target")


def _table_counts(conn) -> dict[str, int]:
    names = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    return {name: conn.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0] for name in names}


def verify_copy(path: Path, key: Optional[bytes], expected_counts: dict[str, int], expected_version: int) -> None:
    """The copy opens with its key, passes `integrity_check` and matches the source's row counts."""
    conn = open_connection(path, key)
    try:
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise AccountDbError(f"Integrity check failed for {path}; the original was not touched.")
        if conn.execute("PRAGMA user_version").fetchone()[0] != expected_version:
            raise AccountDbError(f"Schema version mismatch in {path}; the original was not touched.")
        if _table_counts(conn) != expected_counts:
            raise AccountDbError(f"Row counts differ in {path}; the original was not touched.")
    finally:
        conn.close()


def _remove_sidecars(db_path: Path) -> None:
    for suffix in SIDECAR_SUFFIXES:
        db_path.with_name(db_path.name + suffix).unlink(missing_ok=True)


def encrypt_plaintext_database(db_path: Path, key: bytes, *, keep_plaintext_backup: Optional[Path] = None) -> dict[str, int]:
    """Convert a legacy plaintext `db_path` to an encrypted database in place.

    Steps: refuse unless the file is plaintext; checkpoint and export into a sibling file; verify the
    copy (opens with the key, integrity, row counts, schema version); atomically swap it in. The
    plaintext original is deleted unless `keep_plaintext_backup` names where the operator wants it
    (still plaintext: the caller must warn). Returns the verified row counts."""
    db_path = Path(db_path)
    if not looks_plaintext(db_path):
        raise AccountDbError(f"{db_path} is not a plaintext SQLite database; nothing to convert.")
    src = sqlcipher.connect(str(db_path))
    candidate = private_temp_path(db_path.parent, db_path.name)
    try:
        _checkpoint(src)
        counts = _table_counts(src)
        version = src.execute("PRAGMA user_version").fetchone()[0]
        _export(src, candidate, key)
    finally:
        src.close()
    try:
        verify_copy(candidate, key, counts, version)
        restrict(candidate)
        if keep_plaintext_backup is not None:
            keep_plaintext_backup = Path(keep_plaintext_backup)
            keep_plaintext_backup.parent.mkdir(parents=True, exist_ok=True)
            os.replace(db_path, keep_plaintext_backup)
            restrict(keep_plaintext_backup)
            _remove_sidecars(db_path)
            os.replace(candidate, db_path)
        else:
            _remove_sidecars(db_path)
            os.replace(candidate, db_path)  # atomic: readers see the old or the new file, never half
    except BaseException:
        candidate.unlink(missing_ok=True)
        raise
    restrict(db_path)
    return counts


def rekey_database(db_path: Path, old_key: bytes, new_key_: bytes) -> None:
    """Re-encrypt `db_path` under a new key (SQLCipher `rekey`); verified by reopening with the new key."""
    conn = open_connection(db_path, old_key)
    try:
        _checkpoint(conn)
        counts = _table_counts(conn)
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        conn.execute(key_pragma(new_key_, "rekey"))
    finally:
        conn.close()
    verify_copy(Path(db_path), new_key_, counts, version)
    restrict_database_files(db_path)


def backup_database(db_path: Path, key: bytes, destination: Path) -> dict[str, int]:
    """Write a consistent encrypted copy of a (possibly live) database; refuses to overwrite."""
    destination = Path(destination)
    if destination.exists():
        raise AccountDbError(f"{destination} already exists; backups are never overwritten.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    conn = open_connection(db_path, key)
    candidate = private_temp_path(destination.parent, destination.name)
    try:
        counts = _table_counts(conn)
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        _export(conn, candidate, key)
    finally:
        conn.close()
    try:
        verify_copy(candidate, key, counts, version)
        restrict(candidate)
        os.replace(candidate, destination)
    except BaseException:
        candidate.unlink(missing_ok=True)
        raise
    return counts


def restore_database(backup: Path, key: bytes, db_path: Path) -> Path:
    """Replace `db_path` with a verified backup. The current file is kept as `<name>.pre-restore`.

    The backup must open with `key` (restore with the key the backup was made under). Returns the path
    of the preserved pre-restore file."""
    backup, db_path = Path(backup), Path(db_path)
    probe = open_connection(backup, key)
    try:
        if probe.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise AccountDbError(f"{backup} fails its integrity check; nothing was restored.")
    finally:
        probe.close()
    preserved = db_path.with_name(db_path.name + ".pre-restore")
    candidate = private_temp_path(db_path.parent, db_path.name)
    try:
        candidate.write_bytes(backup.read_bytes())
        restrict(candidate)
        if db_path.exists():
            for suffix in ("", *SIDECAR_SUFFIXES):  # keep the WAL with its database
                current = db_path.with_name(db_path.name + suffix)
                if current.exists():
                    kept = preserved.with_name(preserved.name + suffix)
                    kept.unlink(missing_ok=True)
                    os.replace(current, kept)
                    restrict(kept)
        _remove_sidecars(db_path)
        os.replace(candidate, db_path)
    except BaseException:
        candidate.unlink(missing_ok=True)
        raise
    return preserved
