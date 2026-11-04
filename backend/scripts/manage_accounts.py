#!/usr/bin/env python3
"""OS-operator account commands (PLR-9a, plan §3 *Invitations*).

Runs on the server host against `accounts.db` under `MTG_DATA_DIR` — being able to
run it *is* the authorization, so it is the way to create the very first
invitation on a fresh install (before anyone can sign in to mint one).

  python scripts/manage_accounts.py invite [--role player|admin]
  python scripts/manage_accounts.py list
  python scripts/manage_accounts.py recover NAME
  python scripts/manage_accounts.py create-admin NAME
  python scripts/manage_accounts.py reset-mfa NAME

Data protection (PLR-9e). `accounts.db` is encrypted with SQLCipher; the key lives outside the data
directory (env `MTG_ACCOUNTS_DB_KEY`, or the key file `MTG_ACCOUNTS_DB_KEY_FILE`, default
~/.decklab/accounts.key, mode 600). Stop the server before the commands marked (offline):

  python scripts/manage_accounts.py init-key [--print]           create the key file (fresh install)
  python scripts/manage_accounts.py encrypt-db --yes             convert a legacy plaintext accounts.db (offline)
        [--keep-plaintext-backup PATH]
  python scripts/manage_accounts.py rekey --yes                  rotate the key (offline)
  python scripts/manage_accounts.py backup [--to PATH]           encrypted copy of accounts.db (safe while running)
  python scripts/manage_accounts.py restore BACKUP --yes         replace accounts.db by a backup (offline)
  python scripts/manage_accounts.py status                       encrypted? key found? permissions?

The token is printed once and only its digest is stored. Admin invitations are
redeemed on the `/admin` page (PLR-9d).

`recover` is the password-recovery path (plan section 6: there is no admin-initiated reset). It
prints a single-use credential that expires (`MTG_RECOVERY_TTL_SECONDS`, default one hour),
invalidates every earlier one and authorizes replacing that account's password and nothing else:
the account holder redeems it (`POST /api/auth/recover` for players, `POST /api/admin/recover`
for admins), which ends all sessions and never signs in. Hand it over out of band, never in
logs or support chat. The command is written to the audit log as `operator`.

`create-admin NAME` is the first-admin path for `--online`, where no admin is seeded: it creates the
admin account NAME without a usable password and prints a single-use recovery credential (same
rules as `recover`). The new admin redeems it on `/admin` ("Passwort wiederherstellen", at least 15
characters), signs in and must enrol an authenticator app (MFA is mandatory in `--online`) before
anything else works. `reset-mfa NAME` removes an admin's authenticator and recovery codes (lost
phone and codes); in `--online` that admin must enrol again.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mtg_analyzer import config  # noqa: E402
from mtg_analyzer.services import account_crypto as crypto  # noqa: E402
from mtg_analyzer.services import account_store as acc  # noqa: E402
from mtg_analyzer.services.account_store import (  # noqa: E402
    OPERATOR_CREATOR, ROLE_ADMIN, ROLE_PLAYER, UNUSABLE_PASSWORD_HASH, AccountStore,
)

#: Audit actor for commands run by the OS operator (running the script is the authorization).
OPERATOR_ACTOR = "operator"


def cmd_invite(store: AccountStore, role: str) -> int:
    token = store.create_invitation(OPERATOR_CREATOR, role, enforce_limits=False)
    days = config.INVITE_TTL_SECONDS / 86400
    print(f"Invitation token ({role}, valid {days:g} days, single use) — shown only once:\n\n  {token}\n")
    print("Share it out of band. The invitee enters it in the sign-up form (Profil → Konto → Create account).")
    return 0


def cmd_list(store: AccountStore) -> int:
    rows = store.list_invitations()
    if not rows:
        print("No invitations.")
    for row in rows:
        until = time.strftime("%Y-%m-%d %H:%M", time.localtime(row["expires_at"]))
        print(f"{row['id']}  {row['role']:<6}  {row['state']:<8}  until {until}  creator {row['creator']}")
    return 0


#: Admin names travel in a Basic header (`name:password`), so they cannot contain this separator.
BASIC_SEPARATOR = ":"


def _print_recovery(store: AccountStore, account) -> None:
    token = store.create_recovery(account.player_uuid)
    store.record_audit(OPERATOR_ACTOR, "recovery.issued", f"{account.role}:{account.name}")
    minutes = config.RECOVERY_TTL_SECONDS / 60
    print(f"Recovery credential for {account.name} ({account.role}), valid {minutes:g} minutes, single use,"
          f" shown only once:\n\n  {token}\n")


def cmd_create_admin(store: AccountStore, name: str) -> int:
    try:
        acc.validate_name(name)
        if BASIC_SEPARATOR in name:
            raise acc.InvalidNameError("characters")
    except acc.InvalidNameError as exc:
        print(f"Invalid admin name {name!r}: {exc}", file=sys.stderr)
        return 1
    try:
        account = store.create_account_unchecked(name, UNUSABLE_PASSWORD_HASH, ROLE_ADMIN)
    except acc.NameTakenError:
        print(f"The name {name!r} is taken (or reserved by a recent deletion).", file=sys.stderr)
        return 1
    store.record_audit(OPERATOR_ACTOR, "admin.created", f"admin:{account.name}")
    print(f"Admin account {account.name} created without a usable password.")
    _print_recovery(store, account)
    print("Open /admin, use \"Passwort wiederherstellen\" with this credential (minimum "
          f"{config.ADMIN_PASSWORD_MIN_LENGTH} characters), sign in and enrol the authenticator app.")
    return 0


def cmd_reset_mfa(store: AccountStore, name: str) -> int:
    account = store.get_by_name(name)
    if account is None or account.role != ROLE_ADMIN:
        print(f"No admin named {name!r}.", file=sys.stderr)
        return 1
    removed = store.clear_mfa(account.player_uuid)
    store.record_audit(OPERATOR_ACTOR, "mfa.reset", f"admin:{account.name}")
    print("Authenticator and recovery codes removed." if removed else "That admin had no authenticator.")
    return 0


def cmd_recover(store: AccountStore, name: str) -> int:
    account = store.get_by_name(name)
    if account is None or account.is_default_local:
        print(f"No recoverable account named {name!r}.", file=sys.stderr)
        return 1
    _print_recovery(store, account)
    print("Earlier recovery credentials of this account are now invalid. Deliver it out of band; it can only set a new password.")
    return 0



#: Managed backups are named `accounts-<UTC timestamp>.db`; only those are pruned by `--keep`.
BACKUP_PREFIX = "accounts-"
BACKUP_SUFFIX = ".db"
_TIMESTAMP_FORMAT = "%Y%m%dT%H%M%SZ"


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime(_TIMESTAMP_FORMAT)


def _fail(message: str) -> int:
    print(message, file=sys.stderr)
    return 1


def cmd_init_key(print_key: bool) -> int:
    target = Path(config.ACCOUNTS_DB_KEY_FILE)
    if crypto.key_source() == "env":
        return _fail(f"{config.ACCOUNTS_DB_KEY_ENV} is already set; it takes precedence over a key file.")
    if target.exists():
        return _fail(f"{target} already exists; refusing to replace a key (rotate it with `rekey`).")
    key = crypto.new_key()
    crypto.write_key_file(target, key)
    print(f"Key written to {target} (mode 600).")
    print("BACK THIS FILE UP somewhere other than the data directory. Without it accounts.db cannot be opened.")
    if print_key:
        print(f"{config.ACCOUNTS_DB_KEY_ENV}={key.hex()}")
    return 0


def cmd_encrypt_db(keep_plaintext: Path | None, confirmed: bool) -> int:
    path = config.ACCOUNTS_DB_PATH
    if not confirmed:
        return _fail("Stop the server first, then repeat with --yes.")
    if not path.exists():
        return _fail(f"{path} does not exist; nothing to convert.")
    if not crypto.looks_plaintext(path):
        return _fail(f"{path} is not a plaintext database (already encrypted?). Run `status`.")
    key = crypto.configured_key()
    if key is None:
        key = crypto.new_key()
        crypto.write_key_file(Path(config.ACCOUNTS_DB_KEY_FILE), key)
        print(f"New key written to {config.ACCOUNTS_DB_KEY_FILE} (mode 600). BACK IT UP outside the data directory.")
    counts = crypto.encrypt_plaintext_database(path, key, keep_plaintext_backup=keep_plaintext)
    print(f"Converted {path} to an encrypted database and verified it ({sum(counts.values())} rows in {len(counts)} tables).")
    if keep_plaintext is None:
        print("The plaintext original was removed. Remnants can survive in free disk blocks; on an unencrypted "
              "volume treat the old file contents as exposed to whoever had disk access.")
    else:
        print(f"WARNING: the PLAINTEXT original is kept at {keep_plaintext}. It holds password hashes, session digests "
              "and TOTP secrets unencrypted. Delete it as soon as you have confirmed the server starts, and never "
              "put it in a backup.")
    return 0


def cmd_rekey(confirmed: bool) -> int:
    path = config.ACCOUNTS_DB_PATH
    if not confirmed:
        return _fail("Stop the server first, then repeat with --yes.")
    source = crypto.key_source()
    old = crypto.resolve_key(path)
    new = crypto.new_key()
    key_file = Path(config.ACCOUNTS_DB_KEY_FILE)
    pending = key_file.with_name(key_file.name + ".next")
    if source == "file":
        crypto.write_key_file(pending, new, overwrite=True)  # the new key exists on disk before the DB changes
    crypto.rekey_database(path, old, new)
    if source == "file":
        previous = key_file.with_name(f"{key_file.name}.previous-{_stamp()}")
        os.replace(key_file, previous)
        os.replace(pending, key_file)
        crypto.restrict(previous)
        crypto.restrict(key_file)
        print(f"accounts.db re-encrypted. The old key is kept as {previous}: encrypted backups made before this "
              "need it. Delete it once those backups are gone.")
    else:
        print(f"accounts.db re-encrypted. Set the new value of {config.ACCOUNTS_DB_KEY_ENV} before the next start "
              f"(shown once):\n\n  {new.hex()}\n")
    return 0


def _prune_backups(directory: Path, keep: int) -> list[Path]:
    managed = sorted(p for p in directory.glob(f"{BACKUP_PREFIX}*{BACKUP_SUFFIX}") if p.is_file())
    removed = managed[:-keep] if len(managed) > keep else []
    for old in removed:
        old.unlink()
    return removed


def cmd_backup(destination: Path | None, keep: int) -> int:
    path = config.ACCOUNTS_DB_PATH
    if not path.exists():
        return _fail(f"{path} does not exist.")
    key = crypto.resolve_key(path)
    target = destination or Path(config.ACCOUNTS_BACKUP_DIR) / f"{BACKUP_PREFIX}{_stamp()}{BACKUP_SUFFIX}"
    counts = crypto.backup_database(path, key, target)
    print(f"Encrypted backup written to {target} ({sum(counts.values())} rows). It needs the SAME key to restore.")
    if destination is None:
        crypto.restrict(target.parent, directory=True)
        for old in _prune_backups(target.parent, keep):
            print(f"Removed old backup {old.name} (keeping {keep}).")
    return 0


def cmd_restore(backup: Path, confirmed: bool) -> int:
    if not confirmed:
        return _fail("Stop the server first, then repeat with --yes.")
    key = crypto.configured_key()
    if key is None:
        return _fail("The backup is encrypted: configure the key it was made with "
                     f"({config.ACCOUNTS_DB_KEY_ENV} or {config.ACCOUNTS_DB_KEY_FILE}) first.")
    preserved = crypto.restore_database(backup, key, config.ACCOUNTS_DB_PATH)
    print(f"Restored {config.ACCOUNTS_DB_PATH} from {backup}. The previous file was kept as {preserved}.")
    print("Accounts deleted after this backup are back: delete them again by hand (audit log: player.deleted).")
    return 0


def cmd_status() -> int:
    path = config.ACCOUNTS_DB_PATH
    source = crypto.key_source()
    print(f"database:  {path} ({'missing' if not path.exists() else 'plaintext' if crypto.looks_plaintext(path) else 'encrypted'})")
    print(f"key:       {source or 'NOT CONFIGURED'}" + (f" ({config.ACCOUNTS_DB_KEY_FILE})" if source == "file" else ""))
    if not path.exists():
        return 0 if source else 1
    if crypto.looks_plaintext(path):
        print("PROBLEM: legacy plaintext database; run `encrypt-db`.")
        return 1
    try:
        key = crypto.resolve_key(path)
        conn = crypto.open_connection(path, key)
        conn.close()
    except crypto.AccountDbError as exc:
        return _fail(f"PROBLEM: {exc}")
    print("opens:     yes")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    invite = sub.add_parser("invite", help="create an invitation token")
    invite.add_argument("--role", choices=[ROLE_PLAYER, ROLE_ADMIN], default=ROLE_PLAYER)
    sub.add_parser("list", help="list invitations (metadata only)")
    recover = sub.add_parser("recover", help="issue a single-use password-recovery credential")
    recover.add_argument("name")
    create = sub.add_parser("create-admin", help="create an admin account and issue its first-login credential")
    create.add_argument("name")
    reset = sub.add_parser("reset-mfa", help="remove an admin's authenticator and recovery codes")
    reset.add_argument("name")
    init = sub.add_parser("init-key", help="create the accounts.db key file (fresh install)")
    init.add_argument("--print", dest="print_key", action="store_true", help="also print the key (for the env variable)")
    encrypt = sub.add_parser("encrypt-db", help="convert a legacy plaintext accounts.db to an encrypted one (offline)")
    encrypt.add_argument("--yes", action="store_true", help="the server is stopped")
    encrypt.add_argument("--keep-plaintext-backup", type=Path, default=None, metavar="PATH",
                         help="move the plaintext original here instead of deleting it (WARNING: unencrypted)")
    rekey = sub.add_parser("rekey", help="rotate the accounts.db key (offline)")
    rekey.add_argument("--yes", action="store_true", help="the server is stopped")
    backup = sub.add_parser("backup", help="write an encrypted backup of accounts.db")
    backup.add_argument("--to", type=Path, default=None, metavar="PATH", help="target file (default: backups dir, pruned)")
    backup.add_argument("--keep", type=int, default=config.ACCOUNTS_BACKUP_KEEP, help="managed backups to keep")
    restore = sub.add_parser("restore", help="replace accounts.db by an encrypted backup (offline)")
    restore.add_argument("backup", type=Path)
    restore.add_argument("--yes", action="store_true", help="the server is stopped")
    sub.add_parser("status", help="show whether accounts.db is encrypted and the key is found")
    args = parser.parse_args(argv)
    try:
        return _dispatch(args)
    except crypto.AccountDbError as exc:
        return _fail(f"ERROR: {exc}")


def _dispatch(args) -> int:
    if args.command == "init-key":
        return cmd_init_key(args.print_key)
    if args.command == "encrypt-db":
        return cmd_encrypt_db(args.keep_plaintext_backup, args.yes)
    if args.command == "rekey":
        return cmd_rekey(args.yes)
    if args.command == "backup":
        return cmd_backup(args.to, args.keep)
    if args.command == "restore":
        return cmd_restore(args.backup, args.yes)
    if args.command == "status":
        return cmd_status()
    key = crypto.resolve_key(config.ACCOUNTS_DB_PATH, allow_create=True)
    store = AccountStore(config.ACCOUNTS_DB_PATH, key=key)
    crypto.harden_data_dir(config.DATA_DIR)
    if args.command == "invite":
        return cmd_invite(store, args.role)
    if args.command == "create-admin":
        return cmd_create_admin(store, args.name)
    if args.command == "reset-mfa":
        return cmd_reset_mfa(store, args.name)
    return cmd_recover(store, args.name) if args.command == "recover" else cmd_list(store)


if __name__ == "__main__":
    raise SystemExit(main())
