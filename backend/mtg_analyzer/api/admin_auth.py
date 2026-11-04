"""Per-request administrator authentication (PLR-9d, plan section 6; enforcement point of PLR-17).

There is **no admin session and no admin cookie**: every request carries the admin name and
password in an `Authorization: Basic` header (UTF-8), the server verifies it with the same
`PasswordHasher` as the player login, throttled by *admin identity* (every admin request comes
from loopback, so the source address carries no signal), with generic failures. Player cookies
are never read here, and admin credentials never log into the player UI (`auth.login` refuses
admin roles).

The admin surface is reachable only from the local machine in every run mode
(`network_gate.is_local_request`: loopback peer, no forwarding headers, loopback Host). Remote
administration needs MFA, whose method is still an open decision, so `--online` keeps the whole
surface disabled (`admin_disabled`) instead of shipping a weaker remote path.
"""

from __future__ import annotations

import base64
import binascii
from functools import lru_cache
from typing import Optional

from fastapi import Depends, HTTPException, Request

from mtg_analyzer import config
from mtg_analyzer.api.auth import get_password_hasher
from mtg_analyzer.api.dependencies import get_account_store
from mtg_analyzer.services import account_store as acc
from mtg_analyzer.services import network_gate
from mtg_analyzer.services.password_hasher import PasswordHasher
from mtg_analyzer.services.rate_limiter import FailureLimiter

NO_STORE = {"Cache-Control": "no-store"}

#: Cut for the attempted name before it is used as a throttle key or shown anywhere.
_NAME_KEY_MAX = config.ACCOUNT_NAME_MAX_LENGTH * 4


@lru_cache(maxsize=1)
def get_admin_limiter() -> FailureLimiter:
    return FailureLimiter(config.LOGIN_FAILURE_LIMIT, config.LOGIN_FAILURE_WINDOW_SECONDS)


def deny(status: int, code: str, **headers: str) -> HTTPException:
    return HTTPException(status, {"code": code}, headers={**NO_STORE, **headers})


def require_local_surface(request: Request) -> None:
    """The gate every admin route shares: local machine only, and never in `--online` (no MFA yet)."""
    peer = request.client.host if request.client else None
    headers = {k.lower(): v for k, v in request.headers.items()}
    if not network_gate.is_local_request(peer, headers):
        raise deny(403, "admin_local_only")
    if config.RUN_MODE == "online":
        raise deny(403, "admin_disabled")


def _basic_credentials(request: Request) -> Optional[tuple[str, str]]:
    header = request.headers.get("authorization", "")
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "basic" or not value:
        return None
    try:
        decoded = base64.b64decode(value.strip(), validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None
    name, sep, password = decoded.partition(":")
    if not sep or not name or len(password) > config.PASSWORD_MAX_LENGTH:
        return None
    return name[:_NAME_KEY_MAX], password


def admin_login(
    request: Request,
    store: acc.AccountStore = Depends(get_account_store),
    hasher: PasswordHasher = Depends(get_password_hasher),
    limiter: FailureLimiter = Depends(get_admin_limiter),
) -> acc.Account:
    """Verify the per-request admin credentials; returns the account in any setup state.

    Unknown names, players, the default-localuser, disabled admins and wrong passwords are
    indistinguishable (same status, same time via `dummy_verify`)."""
    require_local_surface(request)
    credentials = _basic_credentials(request)
    if credentials is None:
        raise deny(401, "admin_auth_required")
    name, password = credentials
    ident = f"admin:{acc.normalize_name(name)}"
    wait = limiter.retry_after(ident)
    if wait:
        raise deny(429, "rate_limited", **{"Retry-After": str(int(wait) + 1)})
    account = store.get_by_name(name)
    usable = (
        account is not None and account.role == acc.ROLE_ADMIN and not account.disabled
        and not account.is_default_local
    )
    if usable and hasher.verify(password, account.password_hash):
        limiter.reset(ident)
        return account
    if not usable:
        hasher.dummy_verify(password)
    limiter.record(ident)
    if account is not None and account.role == acc.ROLE_ADMIN:
        # Only attempts against a real admin are logged: a name flood must not grow the audit log.
        store.record_audit(account.name, "admin.auth", result="denied")
    raise deny(401, "admin_auth_required")


def require_admin(account: acc.Account = Depends(admin_login)) -> acc.Account:
    """Dependency for every admin-only operation, including the allowlisted update routes (PLR-17).

    An admin still in initial setup may do nothing but the setup (plan section 6)."""
    if account.setup_required:
        raise deny(403, "setup_required")
    return account


def require_setup_admin(account: acc.Account = Depends(admin_login)) -> acc.Account:
    """The seeded admin during initial setup, and only then."""
    if not account.setup_required:
        raise deny(409, "setup_not_open")
    return account
