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
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mtg_analyzer import config  # noqa: E402
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
    args = parser.parse_args(argv)
    store = AccountStore(config.ACCOUNTS_DB_PATH)
    if args.command == "invite":
        return cmd_invite(store, args.role)
    if args.command == "create-admin":
        return cmd_create_admin(store, args.name)
    if args.command == "reset-mfa":
        return cmd_reset_mfa(store, args.name)
    return cmd_recover(store, args.name) if args.command == "recover" else cmd_list(store)


if __name__ == "__main__":
    raise SystemExit(main())
