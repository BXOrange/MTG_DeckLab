"""SQLite store for accounts, sessions and invitations (PLR-9a).

Lives in its own ``accounts.db`` (plan §3) so credentials never share a file with
deck data. Schema changes are explicit, versioned, additive migrations
(``_MIGRATIONS``); the deck store's schema-hash wipe is deliberately not used here.

Secrets (session tokens, invitation tokens) are 256 random bits from the CSPRNG
and only their SHA-256 digest is stored. Uniqueness of names is enforced by a
unique index on the normalised name, never by a pre-check.
"""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
import threading
import time
import unicodedata
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from mtg_analyzer import config

ROLE_PLAYER = "player"
ROLE_ADMIN = "admin"

#: Names nobody may register (plan §1): built-ins and bot/system identities.
RESERVED_NAMES = frozenset({"local", "admin", "administrator", "system", "bot", "server", "root"})

#: Name of the built-in login-free player of `--localdev` (reserved, plan §1).
DEFAULT_LOCAL_NAME = "local"

#: Stored instead of a hash for accounts that must never verify a password (not a valid scrypt string).
UNUSABLE_PASSWORD_HASH = "!"

#: Bytes of entropy in a session or invitation token (256 bits).
TOKEN_BYTES = 32

_DAY_SECONDS = 24 * 3600

#: Public handle of an invitation in listings: a digest prefix, never enough to redeem it.
INVITATION_ID_LENGTH = 16

#: Public handle of a session in the account's session list (digest prefix).
SESSION_ID_LENGTH = 16

#: The seeded administrator of a fresh install (plan section 6). The initial password is a
#: documented, publicly known constant: it only opens the setup screen, behind the loopback-only
#: `/admin` gate, and is never accepted for anything else (`setup_required`).
INITIAL_ADMIN_NAME = "admin"
INITIAL_ADMIN_PASSWORD = "admin"

#: `meta` key set once the initial admin was seeded, so it is never seeded again (not after a
#: restart and not after the account was removed by the operator).
META_INITIAL_ADMIN_SEEDED = "initial_admin_seeded"

#: Audit text fields are cut to this many characters (names and targets are player-controlled).
AUDIT_FIELD_MAX = 200

_MIGRATIONS: list[str] = [
    """
    CREATE TABLE accounts (
        player_uuid TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        name_norm TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL CHECK (role IN ('player', 'admin')),
        disabled INTEGER NOT NULL DEFAULT 0,
        setup_required INTEGER NOT NULL DEFAULT 0,
        is_default_local INTEGER NOT NULL DEFAULT 0,
        created_at REAL NOT NULL,
        password_changed_at REAL NOT NULL
    );
    CREATE TABLE sessions (
        token_digest TEXT PRIMARY KEY,
        player_uuid TEXT NOT NULL REFERENCES accounts(player_uuid) ON DELETE CASCADE,
        csrf_token TEXT NOT NULL,
        created_at REAL NOT NULL,
        last_seen REAL NOT NULL,
        expires_at REAL NOT NULL,
        revoked_at REAL
    );
    CREATE INDEX sessions_by_account ON sessions(player_uuid);
    CREATE TABLE invitations (
        token_digest TEXT PRIMARY KEY,
        role TEXT NOT NULL CHECK (role IN ('player', 'admin')),
        creator_uuid TEXT NOT NULL,
        created_at REAL NOT NULL,
        expires_at REAL NOT NULL,
        redeemed_by TEXT,
        redeemed_at REAL,
        revoked_at REAL
    );
    CREATE INDEX invitations_by_creator ON invitations(creator_uuid);
    CREATE TABLE name_tombstones (
        name_norm TEXT PRIMARY KEY,
        until REAL NOT NULL
    );
    """,
    # 2 (PLR-9d): one-shot server flags (initial admin seeded), the admin audit log and
    # the OS-operator password-recovery credentials (digest only, single use, expiring).
    """
    CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    CREATE TABLE audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        at REAL NOT NULL,
        actor TEXT NOT NULL,
        action TEXT NOT NULL,
        target TEXT NOT NULL DEFAULT '',
        result TEXT NOT NULL
    );
    CREATE TABLE recovery_credentials (
        token_digest TEXT PRIMARY KEY,
        player_uuid TEXT NOT NULL REFERENCES accounts(player_uuid) ON DELETE CASCADE,
        created_at REAL NOT NULL,
        expires_at REAL NOT NULL,
        consumed_at REAL,
        invalidated_at REAL
    );
    CREATE INDEX recovery_by_account ON recovery_credentials(player_uuid);
    """,
]


class AccountError(Exception):
    """Base class; `code` is a stable machine-readable reason."""

    code = "account_error"


class NameTakenError(AccountError):
    code = "name_taken"


class InvalidNameError(AccountError):
    code = "invalid_name"


class InvalidInvitationError(AccountError):
    """Unknown, expired, used and revoked tokens are deliberately indistinguishable."""

    code = "invalid_invitation"


class InvitationLimitError(AccountError):
    code = "invitation_limit"


@dataclass(frozen=True)
class Account:
    player_uuid: str
    name: str
    role: str
    disabled: bool
    setup_required: bool
    is_default_local: bool
    password_hash: str


@dataclass(frozen=True)
class Session:
    player_uuid: str
    csrf_token: str
    created_at: float
    expires_at: float


def normalize_name(name: str) -> str:
    """NFKC + case-fold + trim (plan §1)."""
    return unicodedata.normalize("NFKC", name).strip().casefold()


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _new_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def validate_name(name: str) -> str:
    """Return the normalised name or raise InvalidNameError."""
    cleaned = unicodedata.normalize("NFKC", name).strip()
    norm = cleaned.casefold()
    if not (config.ACCOUNT_NAME_MIN_LENGTH <= len(cleaned) <= config.ACCOUNT_NAME_MAX_LENGTH):
        raise InvalidNameError("length")
    if any(unicodedata.category(ch)[0] in ("C", "Z") for ch in cleaned.replace(" ", "")) or "  " in cleaned:
        raise InvalidNameError("characters")
    if norm in RESERVED_NAMES:
        raise InvalidNameError("reserved")
    return norm


class AccountStore:
    def __init__(self, path: Path | str, *, clock=None) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._now = clock or time.time
        self._delete_listeners: list = []
        self._deleted: list[str] = []  # PLR-9d: drained by the multiplayer sweeper
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._migrate()

    def _migrate(self) -> None:
        with self._lock:
            version = self._conn.execute("PRAGMA user_version").fetchone()[0]
            for index in range(version, len(_MIGRATIONS)):
                self._conn.execute("BEGIN")
                try:
                    for statement in _MIGRATIONS[index].split(";"):
                        if statement.strip():
                            self._conn.execute(statement)
                    self._conn.execute(f"PRAGMA user_version = {index + 1}")
                    self._conn.execute("COMMIT")
                except Exception:
                    self._conn.execute("ROLLBACK")
                    raise

    @property
    def schema_version(self) -> int:
        return self._conn.execute("PRAGMA user_version").fetchone()[0]

    def close(self) -> None:
        self._conn.close()

    # -- accounts ----------------------------------------------------------

    @staticmethod
    def _account(row: sqlite3.Row | None) -> Optional[Account]:
        if row is None:
            return None
        return Account(
            row["player_uuid"], row["name"], row["role"], bool(row["disabled"]),
            bool(row["setup_required"]), bool(row["is_default_local"]), row["password_hash"],
        )

    def get_by_name(self, name: str) -> Optional[Account]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM accounts WHERE name_norm = ?", (normalize_name(name),)
            ).fetchone()
        return self._account(row)

    def get(self, player_uuid: str) -> Optional[Account]:
        with self._lock:
            row = self._conn.execute("SELECT * FROM accounts WHERE player_uuid = ?", (player_uuid,)).fetchone()
        return self._account(row)

    def count_accounts(self, role: Optional[str] = None) -> int:
        with self._lock:
            if role is None:
                return self._conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
            return self._conn.execute("SELECT COUNT(*) FROM accounts WHERE role = ?", (role,)).fetchone()[0]

    def _insert_account(
        self, name: str, password_hash: str, role: str, *, setup_required: bool = False,
        is_default_local: bool = False, allow_reserved: bool = False,
    ) -> Account:
        cleaned = unicodedata.normalize("NFKC", name).strip()
        norm = normalize_name(name) if allow_reserved else validate_name(name)
        now = self._now()
        tombstone = self._conn.execute("SELECT until FROM name_tombstones WHERE name_norm = ?", (norm,)).fetchone()
        if tombstone is not None and tombstone["until"] > now:
            raise NameTakenError(name)
        player_uuid = str(uuid.uuid4())
        try:
            self._conn.execute(
                "INSERT INTO accounts (player_uuid, name, name_norm, password_hash, role, setup_required,"
                " is_default_local, created_at, password_changed_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (player_uuid, cleaned, norm, password_hash, role, int(setup_required),
                 int(is_default_local), now, now),
            )
        except sqlite3.IntegrityError as exc:
            raise NameTakenError(name) from exc
        self._conn.execute("DELETE FROM name_tombstones WHERE name_norm = ?", (norm,))
        return self.get(player_uuid)  # type: ignore[return-value]

    def create_account_with_invitation(self, name: str, password_hash: str, token: str, role: str) -> Account:
        """Atomically consume an invitation and create the account it entitles (plan §3).

        One transaction: two concurrent signups cannot share one token, and a taken
        name leaves the token unused.
        """
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                now = self._now()
                row = self._conn.execute(
                    "SELECT * FROM invitations WHERE token_digest = ?", (_digest(token),)
                ).fetchone()
                if (row is None or row["role"] != role or row["redeemed_at"] is not None
                        or row["revoked_at"] is not None or row["expires_at"] <= now
                        or not self._creator_active(row["creator_uuid"])):
                    raise InvalidInvitationError()
                account = self._insert_account(name, password_hash, role)
                self._conn.execute(
                    "UPDATE invitations SET redeemed_by = ?, redeemed_at = ? WHERE token_digest = ?",
                    (account.player_uuid, now, row["token_digest"]),
                )
                self._conn.execute("COMMIT")
                return account
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def _creator_active(self, creator_uuid: str) -> bool:
        if creator_uuid == OPERATOR_CREATOR:
            return True
        row = self._conn.execute("SELECT disabled FROM accounts WHERE player_uuid = ?", (creator_uuid,)).fetchone()
        return row is not None and not row["disabled"]

    def create_account_unchecked(
        self, name: str, password_hash: str, role: str, *, setup_required: bool = False,
        is_default_local: bool = False,
    ) -> Account:
        """Operator/seed path: no invitation (initial admin, default-localuser). Reserved names allowed."""
        with self._lock:
            return self._insert_account(
                name, password_hash, role, setup_required=setup_required,
                is_default_local=is_default_local, allow_reserved=True,
            )

    def ensure_default_local(self) -> Account:
        """The built-in `local` player of `--localdev` (plan §1). It has no usable password:
        it can only be signed in by the loopback auto-session, never through /login."""
        with self._lock:
            existing = self.get_by_name(DEFAULT_LOCAL_NAME)
            if existing is not None:
                return existing
            return self._insert_account(
                DEFAULT_LOCAL_NAME, UNUSABLE_PASSWORD_HASH, ROLE_PLAYER,
                is_default_local=True, allow_reserved=True,
            )

    def set_password(self, player_uuid: str, password_hash: str, *, keep_session: Optional[str] = None) -> None:
        """Replace the hash, clear the setup flag and revoke every other session (plan §3)."""
        with self._lock:
            now = self._now()
            self._conn.execute(
                "UPDATE accounts SET password_hash = ?, setup_required = 0, password_changed_at = ? WHERE player_uuid = ?",
                (password_hash, now, player_uuid),
            )
            self._revoke_sessions(player_uuid, except_digest=_digest(keep_session) if keep_session else None)

    def set_disabled(self, player_uuid: str, disabled: bool) -> None:
        with self._lock:
            self._conn.execute("UPDATE accounts SET disabled = ? WHERE player_uuid = ?", (int(disabled), player_uuid))
            if disabled:
                self._revoke_sessions(player_uuid)

    def add_delete_listener(self, listener) -> None:
        """Register ``listener(player_uuid)``, called after an account row is deleted (PLR-16: asset cleanup)."""
        self._delete_listeners.append(listener)

    def delete_account(self, player_uuid: str) -> None:
        """Remove an account and start its name tombstone (plan §6); delete listeners then clean up its data."""
        with self._lock:
            row = self._conn.execute("SELECT name_norm FROM accounts WHERE player_uuid = ?", (player_uuid,)).fetchone()
            if row is None:
                return
            self._conn.execute("DELETE FROM accounts WHERE player_uuid = ?", (player_uuid,))
            self._conn.execute(
                "INSERT OR REPLACE INTO name_tombstones (name_norm, until) VALUES (?, ?)",
                (row["name_norm"], self._now() + config.NAME_TOMBSTONE_SECONDS),
            )
            self._deleted.append(player_uuid)
        for listener in self._delete_listeners:
            listener(player_uuid)

    # -- administration (PLR-9d) --------------------------------------------

    def seed_initial_admin(self, password_hash: str) -> Optional[Account]:
        """Seed `admin`/`admin` (flagged `setup_required`) once, on an empty admin table.

        Returns the new account, or None when an admin already exists or the seed ran before
        (the `meta` flag survives the account, so a deleted admin is never silently re-created
        with the public password; the OS-operator command creates the next one).
        """
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                seeded = self._conn.execute(
                    "SELECT 1 FROM meta WHERE key = ?", (META_INITIAL_ADMIN_SEEDED,)
                ).fetchone()
                admins = self._conn.execute(
                    "SELECT COUNT(*) FROM accounts WHERE role = 'admin'"
                ).fetchone()[0]
                if seeded is not None or admins:
                    self._conn.execute("ROLLBACK")
                    return None
                account = self._insert_account(
                    INITIAL_ADMIN_NAME, password_hash, ROLE_ADMIN, setup_required=True, allow_reserved=True
                )
                self._conn.execute(
                    "INSERT INTO meta (key, value) VALUES (?, '1')", (META_INITIAL_ADMIN_SEEDED,)
                )
                self._conn.execute("COMMIT")
                return account
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def setup_open(self) -> bool:
        """Whether an admin still carries the initial credential (`setup_required`)."""
        with self._lock:
            return self._conn.execute(
                "SELECT 1 FROM accounts WHERE role = 'admin' AND setup_required = 1 LIMIT 1"
            ).fetchone() is not None

    def complete_setup(self, player_uuid: str, password_hash: str) -> bool:
        """Replace the initial password and clear `setup_required` in one conditional UPDATE.

        False when the admin was not in setup (already completed, or a concurrent request won)."""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE accounts SET password_hash = ?, setup_required = 0, password_changed_at = ?"
                " WHERE player_uuid = ? AND role = 'admin' AND setup_required = 1",
                (password_hash, self._now(), player_uuid),
            )
            if cur.rowcount != 1:
                return False
            self._revoke_sessions(player_uuid)
            return True

    def list_players(self, query: str = "", *, limit: int, offset: int = 0) -> tuple[list[dict], int]:
        """Player accounts (never admins), newest first, optionally filtered by a name fragment."""
        needle = normalize_name(query) if query else ""
        with self._lock:
            now = self._now()
            where = "role = 'player'" + (" AND instr(name_norm, ?) > 0" if needle else "")
            params: tuple = (needle,) if needle else ()
            total = self._conn.execute(f"SELECT COUNT(*) FROM accounts WHERE {where}", params).fetchone()[0]
            rows = self._conn.execute(
                f"SELECT player_uuid, name, disabled, is_default_local, created_at FROM accounts WHERE {where}"
                " ORDER BY created_at DESC, name_norm LIMIT ? OFFSET ?", params + (limit, offset),
            ).fetchall()
            live = {
                r["player_uuid"]: r["n"] for r in self._conn.execute(
                    "SELECT player_uuid, COUNT(*) AS n FROM sessions WHERE revoked_at IS NULL AND expires_at > ?"
                    " GROUP BY player_uuid", (now,),
                )
            }
        return [
            {"player_uuid": r["player_uuid"], "name": r["name"], "disabled": bool(r["disabled"]),
             "is_default_local": bool(r["is_default_local"]), "created_at": r["created_at"],
             "sessions": live.get(r["player_uuid"], 0)}
            for r in rows
        ], total

    def count_live_sessions(self, player_uuid: str) -> int:
        return len(self.list_sessions(player_uuid))

    def drain_deleted(self) -> list[str]:
        """Account ids deleted since the last call, for the multiplayer sweeper (frees their seats)."""
        with self._lock:
            deleted, self._deleted = self._deleted, []
        return deleted

    # -- audit log (plan section 6: actor, action, target, timestamp, result; no secrets) -----------

    @staticmethod
    def _audit_text(value: str) -> str:
        cleaned = "".join(" " if unicodedata.category(ch)[0] == "C" else ch for ch in str(value))
        return cleaned[:AUDIT_FIELD_MAX]

    def record_audit(self, actor: str, action: str, target: str = "", result: str = "ok") -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO audit_log (at, actor, action, target, result) VALUES (?,?,?,?,?)",
                (self._now(), self._audit_text(actor), self._audit_text(action),
                 self._audit_text(target), self._audit_text(result)),
            )

    def list_audit(self, *, limit: int, offset: int = 0) -> tuple[list[dict], int]:
        with self._lock:
            total = self._conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
            rows = self._conn.execute(
                "SELECT id, at, actor, action, target, result FROM audit_log ORDER BY id DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [dict(r) for r in rows], total

    # -- password recovery (OS-operator credential, plan section 6) ---------

    def create_recovery(self, player_uuid: str) -> str:
        """Issue a recovery credential (shown once, digest stored) and invalidate earlier ones.

        It authorizes replacing this account's password and nothing else (`redeem_recovery`)."""
        with self._lock:
            now = self._now()
            self._conn.execute(
                "UPDATE recovery_credentials SET invalidated_at = ? WHERE player_uuid = ?"
                " AND consumed_at IS NULL AND invalidated_at IS NULL", (now, player_uuid),
            )
            token = _new_token()
            self._conn.execute(
                "INSERT INTO recovery_credentials (token_digest, player_uuid, created_at, expires_at)"
                " VALUES (?,?,?,?)", (_digest(token), player_uuid, now, now + config.RECOVERY_TTL_SECONDS),
            )
        return token

    def redeem_recovery(self, name: str, token: str, password_hash: str, role: str) -> bool:
        """Atomically consume a recovery credential and replace the password.

        Revokes every session; never signs in. Unknown name, wrong role, disabled account,
        unknown/used/expired/invalidated token all return the same False."""
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                now = self._now()
                account = self.get_by_name(name)
                row = None
                if account is not None and account.role == role and not account.disabled and not account.is_default_local:
                    row = self._conn.execute(
                        "SELECT * FROM recovery_credentials WHERE token_digest = ? AND player_uuid = ?",
                        (_digest(token), account.player_uuid),
                    ).fetchone()
                if (row is None or row["consumed_at"] is not None or row["invalidated_at"] is not None
                        or row["expires_at"] <= now):
                    self._conn.execute("ROLLBACK")
                    return False
                self._conn.execute(
                    "UPDATE recovery_credentials SET consumed_at = ? WHERE token_digest = ?", (now, row["token_digest"])
                )
                self._conn.execute(
                    "UPDATE accounts SET password_hash = ?, setup_required = 0, password_changed_at = ?"
                    " WHERE player_uuid = ?", (password_hash, now, account.player_uuid),
                )
                self._revoke_sessions(account.player_uuid)
                self._conn.execute("COMMIT")
                return True
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    # -- sessions ----------------------------------------------------------

    def create_session(self, player_uuid: str) -> tuple[str, Session]:
        """Return the raw token (set as the cookie, never stored) and its server-side record."""
        token = _new_token()
        csrf = _new_token()
        now = self._now()
        expires = now + config.SESSION_IDLE_SECONDS
        with self._lock:
            self._conn.execute(
                "INSERT INTO sessions (token_digest, player_uuid, csrf_token, created_at, last_seen, expires_at)"
                " VALUES (?,?,?,?,?,?)",
                (_digest(token), player_uuid, csrf, now, now, expires),
            )
        return token, Session(player_uuid, csrf, now, expires)

    def resolve_session(self, token: str) -> Optional[tuple[Account, Session]]:
        """Validate idle/absolute expiry, revocation and account state; slide the idle window."""
        if not token:
            return None
        with self._lock:
            now = self._now()
            row = self._conn.execute(
                "SELECT * FROM sessions WHERE token_digest = ?", (_digest(token),)
            ).fetchone()
            if row is None or row["revoked_at"] is not None or row["expires_at"] <= now:
                return None
            if row["created_at"] + config.SESSION_ABSOLUTE_SECONDS <= now:
                return None
            account = self.get(row["player_uuid"])
            if account is None or account.disabled:
                return None
            expires = min(now + config.SESSION_IDLE_SECONDS, row["created_at"] + config.SESSION_ABSOLUTE_SECONDS)
            self._conn.execute(
                "UPDATE sessions SET last_seen = ?, expires_at = ? WHERE token_digest = ?",
                (now, expires, row["token_digest"]),
            )
        return account, Session(row["player_uuid"], row["csrf_token"], row["created_at"], expires)

    def session_valid(self, token: str) -> bool:
        """Whether ``token`` is still a live session, **without** sliding its idle window.

        Long-lived connections (the multiplayer socket, PLR-9c) re-check this to notice
        logout, expiry, disablement and deletion; polling must not keep a session alive,
        so unlike `resolve_session` it never writes.
        """
        if not token:
            return False
        with self._lock:
            now = self._now()
            row = self._conn.execute(
                "SELECT * FROM sessions WHERE token_digest = ?", (_digest(token),)
            ).fetchone()
            if row is None or row["revoked_at"] is not None or row["expires_at"] <= now:
                return False
            if row["created_at"] + config.SESSION_ABSOLUTE_SECONDS <= now:
                return False
            account = self.get(row["player_uuid"])
            return account is not None and not account.disabled

    def revoke_session(self, token: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE sessions SET revoked_at = ? WHERE token_digest = ? AND revoked_at IS NULL",
                (self._now(), _digest(token)),
            )

    def list_sessions(self, player_uuid: str) -> list[dict]:
        """Live sessions of one account, metadata only (plan §3: sessions listed in the UI).

        `id` is a digest prefix: enough to revoke that session, never enough to use it."""
        with self._lock:
            now = self._now()
            rows = self._conn.execute(
                "SELECT token_digest, created_at, last_seen, expires_at FROM sessions WHERE player_uuid = ?"
                " AND revoked_at IS NULL AND expires_at > ? ORDER BY last_seen DESC",
                (player_uuid, now),
            ).fetchall()
        return [
            {"id": r["token_digest"][:SESSION_ID_LENGTH], "created_at": r["created_at"],
             "last_seen": r["last_seen"], "expires_at": r["expires_at"]}
            for r in rows
        ]

    def revoke_session_by_id(self, player_uuid: str, session_id: str) -> bool:
        """Revoke one of this account's own sessions by its listed `id` prefix."""
        if len(session_id) < SESSION_ID_LENGTH or any(c not in "0123456789abcdef" for c in session_id):
            return False
        with self._lock:
            cur = self._conn.execute(
                "UPDATE sessions SET revoked_at = ? WHERE player_uuid = ? AND token_digest LIKE ?"
                " AND revoked_at IS NULL", (self._now(), player_uuid, session_id + "%"),
            )
            return cur.rowcount > 0

    def revoke_all_sessions(self, player_uuid: str) -> None:
        with self._lock:
            self._revoke_sessions(player_uuid)

    def _revoke_sessions(self, player_uuid: str, *, except_digest: Optional[str] = None) -> None:
        self._conn.execute(
            "UPDATE sessions SET revoked_at = ? WHERE player_uuid = ? AND revoked_at IS NULL"
            " AND token_digest != ?",
            (self._now(), player_uuid, except_digest or ""),
        )

    # -- invitations -------------------------------------------------------

    def create_invitation(self, creator_uuid: str, role: str, *, enforce_limits: bool = True) -> str:
        """Return the raw token (shown once). Player creators are capped (plan §3)."""
        with self._lock:
            now = self._now()
            if enforce_limits:
                outstanding = self._conn.execute(
                    "SELECT COUNT(*) FROM invitations WHERE creator_uuid = ? AND redeemed_at IS NULL"
                    " AND revoked_at IS NULL AND expires_at > ?", (creator_uuid, now),
                ).fetchone()[0]
                today = self._conn.execute(
                    "SELECT COUNT(*) FROM invitations WHERE creator_uuid = ? AND created_at > ?",
                    (creator_uuid, now - _DAY_SECONDS),
                ).fetchone()[0]
                if (outstanding >= config.INVITE_MAX_OUTSTANDING_PER_PLAYER
                        or today >= config.INVITE_MAX_PER_DAY_PER_PLAYER):
                    raise InvitationLimitError()
            token = _new_token()
            self._conn.execute(
                "INSERT INTO invitations (token_digest, role, creator_uuid, created_at, expires_at)"
                " VALUES (?,?,?,?,?)",
                (_digest(token), role, creator_uuid, now, now + config.INVITE_TTL_SECONDS),
            )
        return token

    def revoke_invitation(self, token_digest: str, *, by: str, is_admin: bool) -> bool:
        """Revoke by full digest or by the listed `id` prefix (hex only, min 16 characters)."""
        if len(token_digest) < INVITATION_ID_LENGTH or any(c not in "0123456789abcdef" for c in token_digest):
            return False
        with self._lock:
            row = self._conn.execute(
                "SELECT token_digest, creator_uuid FROM invitations WHERE token_digest LIKE ?",
                (token_digest + "%",),
            ).fetchone()
            token_digest = row["token_digest"] if row else token_digest
            if row is None or not (is_admin or row["creator_uuid"] == by):
                return False
            self._conn.execute(
                "UPDATE invitations SET revoked_at = ? WHERE token_digest = ? AND revoked_at IS NULL",
                (self._now(), token_digest),
            )
            return True

    def list_invitations(self, creator_uuid: Optional[str] = None) -> list[dict]:
        """Metadata only; an issued token can never be read back (plan §6)."""
        with self._lock:
            now = self._now()
            sql = "SELECT * FROM invitations"
            params: tuple = ()
            if creator_uuid is not None:
                sql += " WHERE creator_uuid = ?"
                params = (creator_uuid,)
            rows = self._conn.execute(sql + " ORDER BY created_at DESC", params).fetchall()
        def state(r: sqlite3.Row) -> str:
            if r["redeemed_at"] is not None:
                return "used"
            if r["revoked_at"] is not None:
                return "revoked"
            return "expired" if r["expires_at"] <= now else "open"
        return [
            {"id": r["token_digest"][:INVITATION_ID_LENGTH], "role": r["role"], "creator": r["creator_uuid"],
             "state": state(r), "created_at": r["created_at"], "expires_at": r["expires_at"]}
            for r in rows
        ]


#: Creator id for tokens minted by the OS-operator command rather than an account.
OPERATOR_CREATOR = "operator"
