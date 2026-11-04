"""Per-request administrator authentication (PLR-9d, plan section 6; enforcement point of PLR-17).

There is **no admin session and no admin cookie**: every request carries the admin name and
password in an `Authorization: Basic` header (UTF-8), the server verifies it with the same
`PasswordHasher` as the player login, throttled by *admin identity* (every local admin request
comes from loopback, so the source address carries no signal), with generic failures. Player
cookies are never read here, and admin credentials never log into the player UI (`auth.login`
refuses admin roles).

Where it is reachable (`network_gate.admin_surface_refusal`): the local machine in every run
mode (behind `--behind-tls-proxy` via the dedicated loopback-only admin listener,
`api/admin_listener.py`); additionally, in `--online` only, remote clients over HTTPS. LAN and
localdev stay loopback-only.

Second factor (TOTP, `services/totp.py`), **remote requests only** (PLR-19): a local request needs
name + password and nothing else, whether or not the admin enrolled. A remote admin who enrolled an
authenticator must present a code with the password. `--online` requires enrolment before remote
use: an admin without one can reach nothing remotely but the enrolment routes
(`mfa_enrollment_required`). The code travels in `X-Admin-OTP` (an
authenticator code or a single-use recovery code; each TOTP time step is accepted once). Because
one code cannot cover a page's many requests, `POST /api/admin/mfa/grant` trades one verified
code for a short-lived, server-held, request-bound grant sent in `X-Admin-Grant` next to the
password (`services/admin_grants.py`); there is still no cookie.
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
from mtg_analyzer.services import network_gate, security_log
from mtg_analyzer.services.admin_grants import AdminGrants, binding_for
from mtg_analyzer.services.password_hasher import PasswordHasher
from mtg_analyzer.services.rate_limiter import FailureLimiter

NO_STORE = {"Cache-Control": "no-store"}

#: Request headers of the second factor (see module docstring).
OTP_HEADER = "x-admin-otp"
GRANT_HEADER = "x-admin-grant"

#: `request.state.admin_mfa` values: how the second factor of this request was satisfied.
MFA_VIA_OTP = "otp"
MFA_VIA_RECOVERY = "recovery"
MFA_VIA_GRANT = "grant"

#: Cut for the attempted name before it is used as a throttle key or shown anywhere.
_NAME_KEY_MAX = config.ACCOUNT_NAME_MAX_LENGTH * 4


@lru_cache(maxsize=1)
def get_admin_limiter() -> FailureLimiter:
    return FailureLimiter(config.LOGIN_FAILURE_LIMIT, config.LOGIN_FAILURE_WINDOW_SECONDS)


def deny(status: int, code: str, **headers: str) -> HTTPException:
    return HTTPException(status, {"code": code}, headers={**NO_STORE, **headers})


@lru_cache(maxsize=1)
def get_admin_grants() -> AdminGrants:
    return AdminGrants()


def on_admin_listener(request: Request) -> bool:
    """Whether the request arrived on the dedicated loopback-only admin listener (PLR-19)."""
    return bool(request.scope.get(network_gate.ADMIN_LISTENER_SCOPE_KEY))


def require_local_surface(request: Request) -> None:
    """The gate every admin route shares: local machine, or HTTPS in `--online` (MFA is checked at login)."""
    peer = request.client.host if request.client else None
    headers = {k.lower(): v for k, v in request.headers.items()}
    refusal = network_gate.admin_surface_refusal(peer, headers, request.url.scheme, admin_listener=on_admin_listener(request))
    if refusal is not None:
        raise deny(403, refusal)


def is_remote(request: Request) -> bool:
    """True for a request that is not from the server machine itself (PLR-19: only remote ones need a second factor)."""
    peer = request.client.host if request.client else None
    return not network_gate.is_local_request(
        peer, {k.lower(): v for k, v in request.headers.items()}, admin_listener=on_admin_listener(request)
    )


def client_key(request: Request) -> str:
    """Address a grant is bound to: the TCP peer, plus the client a *trusted* proxy reports (BUG-52)."""
    peer = request.client.host if request.client else "unknown"
    forwarded = network_gate.forwarded_client(peer, {k.lower(): v for k, v in request.headers.items()})
    return f"{peer}|{forwarded}" if forwarded else peer


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


def _second_factor(
    request: Request, account: acc.Account, store: acc.AccountStore, grants: AdminGrants,
    limiter: FailureLimiter, keys: tuple[str, ...],
) -> None:
    """Enforce the authenticator code for an enrolled admin (after the password was right).

    A local request (PLR-19) never needs a second factor, enrolled or not: name + password only.
    Not enrolled: nothing to check here (`require_admin` refuses an unenrolled admin's remote use in `--online`).
    A wrong code counts against the throttle and is audited; a missing one is a plain 401 that
    only a correct password reaches."""
    request.state.admin_mfa = None
    if not is_remote(request):
        return
    mfa = store.get_mfa(account.player_uuid)
    if not mfa.enrolled:
        return
    binding = binding_for(account.password_hash, mfa.version)
    grant = request.headers.get(GRANT_HEADER, "")
    if grant and grants.check(grant, account.player_uuid, client_key(request), binding):
        request.state.admin_mfa = MFA_VIA_GRANT
        return
    otp = request.headers.get(OTP_HEADER, "")
    if not otp:
        raise deny(401, "admin_otp_required")
    kind = store.consume_second_factor(account.player_uuid, otp)
    if kind is None:
        limiter.record(*keys)
        store.record_audit(account.name, "admin.auth", result="denied (second factor)")
        raise deny(401, "admin_auth_required")
    request.state.admin_mfa = MFA_VIA_RECOVERY if kind == "recovery" else MFA_VIA_OTP
    if kind == "recovery":
        store.record_audit(account.name, "admin.recovery_code_used", result="ok")


def admin_login(
    request: Request,
    store: acc.AccountStore = Depends(get_account_store),
    hasher: PasswordHasher = Depends(get_password_hasher),
    limiter: FailureLimiter = Depends(get_admin_limiter),
    grants: AdminGrants = Depends(get_admin_grants),
) -> acc.Account:
    """Verify the per-request admin credentials; returns the account in any setup state.

    Unknown names, players, the default-localuser, disabled admins and wrong passwords are
    indistinguishable (same status, same time via `dummy_verify`). Remote (`--online`) requests are
    also throttled per source address."""
    require_local_surface(request)
    credentials = _basic_credentials(request)
    if credentials is None:
        raise deny(401, "admin_auth_required")
    name, password = credentials
    ident = f"admin:{acc.normalize_name(name)}"
    keys = (ident, f"src:{client_key(request)}") if is_remote(request) else (ident,)
    wait = limiter.retry_after(*keys)
    if wait:
        raise deny(429, "rate_limited", **{"Retry-After": str(int(wait) + 1)})
    account = store.get_by_name(name)
    usable = (
        account is not None and account.role == acc.ROLE_ADMIN and not account.disabled
        and not account.is_default_local
    )
    if usable and hasher.verify(password, account.password_hash):
        _second_factor(request, account, store, grants, limiter, keys)
        limiter.reset(ident)
        return account
    if not usable:
        hasher.dummy_verify(password)
    limiter.record(*keys)
    security_log.event("admin.auth", outcome="failure", source=client_key(request), name=name)
    if account is not None and account.role == acc.ROLE_ADMIN:
        # Only attempts against a real admin are logged: a name flood must not grow the audit log.
        store.record_audit(account.name, "admin.auth", result="denied")
    raise deny(401, "admin_auth_required")


def require_admin(
    request: Request, account: acc.Account = Depends(admin_login),
    store: acc.AccountStore = Depends(get_account_store),
) -> acc.Account:
    """Dependency for every admin-only operation, including the allowlisted update routes (PLR-17).

    An admin still in initial setup may do nothing but the setup (plan section 6); in `--online`
    an admin who has not enrolled an authenticator may do nothing remotely but enrol; locally (PLR-19)
    they work with name + password and enrol before their first remote use."""
    if account.setup_required:
        raise deny(403, "setup_required")
    if config.RUN_MODE == "online" and is_remote(request) and not store.get_mfa(account.player_uuid).enrolled:
        raise deny(403, "mfa_enrollment_required")
    request.state.actor = account.player_uuid  # read by SecurityEventMiddleware (PLR-9e)
    return account


def require_setup_admin(account: acc.Account = Depends(admin_login)) -> acc.Account:
    """The seeded admin during initial setup, and only then."""
    if not account.setup_required:
        raise deny(409, "setup_not_open")
    return account
