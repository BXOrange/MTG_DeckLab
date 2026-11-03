#!/usr/bin/env python3
"""OS-operator account commands (PLR-9a, plan §3 *Invitations*).

Runs on the server host against `accounts.db` under `MTG_DATA_DIR` — being able to
run it *is* the authorization, so it is the way to create the very first
invitation on a fresh install (before anyone can sign in to mint one).

  python scripts/manage_accounts.py invite [--role player|admin]
  python scripts/manage_accounts.py list

The token is printed once and only its digest is stored. Admin invitations are
redeemed on the `/admin` page (PLR-9d); until then only `player` tokens are usable.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mtg_analyzer import config  # noqa: E402
from mtg_analyzer.services.account_store import OPERATOR_CREATOR, ROLE_ADMIN, ROLE_PLAYER, AccountStore  # noqa: E402


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    invite = sub.add_parser("invite", help="create an invitation token")
    invite.add_argument("--role", choices=[ROLE_PLAYER, ROLE_ADMIN], default=ROLE_PLAYER)
    sub.add_parser("list", help="list invitations (metadata only)")
    args = parser.parse_args(argv)
    store = AccountStore(config.ACCOUNTS_DB_PATH)
    return cmd_invite(store, args.role) if args.command == "invite" else cmd_list(store)


if __name__ == "__main__":
    raise SystemExit(main())
