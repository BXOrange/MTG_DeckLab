"""Account API: signup by invitation, login, logout, password change, invitations (PLR-9a).

Plan: docs/concepts/15_ACCOUNT_SYSTEM_PLAN.md §3. Identity comes from one dependency,
`current_account`; a cookie-bearing unsafe request must carry the session-bound CSRF
token in `X-CSRF-Token`. Login failures are generic (no enumeration, comparable timing
via `dummy_verify`), and failures are throttled per source and per account name.
Admin accounts never log in here (plan §6, separate identities).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, WebSocket
from pydantic import BaseModel, ConfigDict, Field

from mtg_analyzer import config
from mtg_analyzer.api.dependencies import get_account_store
from mtg_analyzer.services import account_store as acc
from mtg_analyzer.services import network_gate
from mtg_analyzer.services import password_policy as policy
from mtg_analyzer.services.password_hasher import PasswordHasher
from mtg_analyzer.services.rate_limiter import FailureLimiter

router = APIRouter(prefix="/api/auth", tags=["auth"])

#: Cookie names: online uses a host-only `__Host-` cookie (needs Secure); over plain HTTP
#: in LAN/localdev that prefix is impossible, so a distinct name is used (plan §3).
SESSION_COOKIE_ONLINE = "__Host-mtg_session"
SESSION_COOKIE_LAN = "mtg_session"
CSRF_HEADER = "x-csrf-token"

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def session_cookie_name() -> str:
    return SESSION_COOKIE_ONLINE if config.RUN_MODE == "online" else SESSION_COOKIE_LAN


@lru_cache(maxsize=1)
def get_password_hasher() -> PasswordHasher:
    return PasswordHasher()


@lru_cache(maxsize=1)
def get_login_limiter() -> FailureLimiter:
    return FailureLimiter(config.LOGIN_FAILURE_LIMIT, config.LOGIN_FAILURE_WINDOW_SECONDS)


@lru_cache(maxsize=1)
def get_signup_limiter() -> FailureLimiter:
    return FailureLimiter(config.SIGNUP_ATTEMPT_LIMIT, config.LOGIN_FAILURE_WINDOW_SECONDS)


@dataclass(frozen=True)
class AuthContext:
    account: acc.Account
    session: acc.Session
    token: str


#: Set when the default-localuser logs out, so the loopback auto-session does not sign it
#: straight back in (plan §1: it "can log out and be replaced by a real player login").
LOCALUSER_OPT_OUT_COOKIE = "mtg_localuser_off"


def _auto_localuser(request: Request, response: Response, store: acc.AccountStore) -> Optional[AuthContext]:
    """`--localdev` only: sign the default-localuser in for genuinely local requests."""
    if config.RUN_MODE != "localdev" or request.cookies.get(LOCALUSER_OPT_OUT_COOKIE):
        return None
    peer = request.client.host if request.client else None
    if not network_gate.is_local_request(peer, {k.lower(): v for k, v in request.headers.items()}):
        return None
    account = store.ensure_default_local()
    token, session = store.create_session(account.player_uuid)
    _set_cookie(response, token)
    return AuthContext(account, session, token)


def current_context(
    request: Request, response: Response, store: acc.AccountStore = Depends(get_account_store)
) -> Optional[AuthContext]:
    """The signed-in player, or None. Enforces CSRF for unsafe methods (plan §3)."""
    token = request.cookies.get(session_cookie_name(), "")
    resolved = store.resolve_session(token)
    if resolved is None:
        return _auto_localuser(request, response, store)
    account, session = resolved
    if account.role != acc.ROLE_PLAYER:
        return None
    if request.method.upper() not in _SAFE_METHODS:
        sent = request.headers.get(CSRF_HEADER, "")
        if not sent or not _constant_time_equal(sent, session.csrf_token):
            raise HTTPException(403, {"code": "csrf"})
    return AuthContext(account, session, token)


def websocket_context(
    websocket: WebSocket, store: acc.AccountStore = Depends(get_account_store)
) -> Optional[AuthContext]:
    """The signed-in player behind a WebSocket upgrade (PLR-9c), or None.

    Cookie only: the handshake has no response to set a cookie on, so the `--localdev`
    default-localuser is signed in by the page's first HTTP call (`/api/auth/me`), never here.
    Origin is vetted earlier by `request_guard`. No CSRF check: a handshake is a GET, and
    cross-site hijacking is the Origin check's job (plan section 5).
    """
    token = websocket.cookies.get(session_cookie_name(), "")
    resolved = store.resolve_session(token)
    if resolved is None:
        return None
    account, session = resolved
    if account.role != acc.ROLE_PLAYER:
        return None
    return AuthContext(account, session, token)


def current_account(ctx: Optional[AuthContext] = Depends(current_context)) -> AuthContext:
    """Dependency for routes that need a login (401 otherwise)."""
    if ctx is None:
        raise HTTPException(401, {"code": "unauthenticated"})
    return ctx


def _constant_time_equal(a: str, b: str) -> bool:
    import hmac
    return hmac.compare_digest(a.encode(), b.encode())


def _source(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _set_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        session_cookie_name(), token,
        max_age=int(config.SESSION_ABSOLUTE_SECONDS),  # cookie lifetime <= server lifetime
        httponly=True, samesite="lax", secure=config.RUN_MODE == "online", path="/",
    )


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


def _account_view(account: acc.Account, session: acc.Session) -> dict:
    return {
        "authenticated": True,
        "player_uuid": account.player_uuid,
        "name": account.name,
        "csrf_token": session.csrf_token,
    }


class SignupBody(BaseModel):
    model_config = ConfigDict(extra="forbid")  # a client can never submit a role
    name: str = Field(max_length=config.ACCOUNT_NAME_MAX_LENGTH * 4)
    password: str = Field(max_length=config.PASSWORD_MAX_LENGTH + 1)
    invitation: str = Field(max_length=256)


class LoginBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(max_length=config.ACCOUNT_NAME_MAX_LENGTH * 4)
    password: str = Field(max_length=config.PASSWORD_MAX_LENGTH + 1)


class PasswordChangeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: str = Field(max_length=config.PASSWORD_MAX_LENGTH + 1)
    new_password: str = Field(max_length=config.PASSWORD_MAX_LENGTH + 1)


@router.get("/policy")
def password_policy() -> dict:
    """Constants the frontend meter mirrors; the server stays authoritative."""
    return {
        "min_length": config.PASSWORD_MIN_LENGTH,
        "green_length": max(config.PASSWORD_GREEN_LENGTH, config.PASSWORD_MIN_LENGTH),
        "max_length": config.PASSWORD_MAX_LENGTH,
        "name_min_length": config.ACCOUNT_NAME_MIN_LENGTH,
        "name_max_length": config.ACCOUNT_NAME_MAX_LENGTH,
    }


@router.get("/me")
def me(response: Response, ctx: Optional[AuthContext] = Depends(current_context)) -> dict:
    _no_store(response)
    if ctx is None:
        return {"authenticated": False}
    return _account_view(ctx.account, ctx.session)


@router.post("/signup", status_code=201)
def signup(
    body: SignupBody, request: Request, response: Response,
    store: acc.AccountStore = Depends(get_account_store),
    hasher: PasswordHasher = Depends(get_password_hasher),
    limiter: FailureLimiter = Depends(get_signup_limiter),
) -> dict:
    _no_store(response)
    source = f"signup:{_source(request)}"
    wait = limiter.retry_after(source)
    if wait:
        raise HTTPException(429, {"code": "rate_limited"}, headers={"Retry-After": str(int(wait) + 1)})
    problem = policy.check(body.password, name=body.name)
    if problem is not None:
        raise HTTPException(400, {"code": f"password_{problem}"})
    try:
        acc.validate_name(body.name)
    except acc.InvalidNameError as exc:
        raise HTTPException(400, {"code": exc.code})
    limiter.record(source)  # every redemption attempt counts: token guessing is bounded
    try:
        account = store.create_account_with_invitation(
            body.name, hasher.hash(body.password), body.invitation, acc.ROLE_PLAYER
        )
    except acc.NameTakenError:
        raise HTTPException(409, {"code": "name_taken"})
    except acc.InvalidInvitationError:
        raise HTTPException(400, {"code": "invalid_invitation"})
    token, session = store.create_session(account.player_uuid)
    _set_cookie(response, token)
    return _account_view(account, session)


@router.post("/login")
def login(
    body: LoginBody, request: Request, response: Response,
    store: acc.AccountStore = Depends(get_account_store),
    hasher: PasswordHasher = Depends(get_password_hasher),
    limiter: FailureLimiter = Depends(get_login_limiter),
) -> dict:
    _no_store(response)
    source = f"src:{_source(request)}"
    ident = f"name:{acc.normalize_name(body.name)}"
    wait = limiter.retry_after(source, ident)
    if wait:
        raise HTTPException(429, {"code": "rate_limited"}, headers={"Retry-After": str(int(wait) + 1)})
    account = store.get_by_name(body.name)
    # Unknown, disabled, admin and default-localuser accounts all take the same path and
    # the same time as a wrong password (plan §3 generic failures).
    usable = (
        account is not None and not account.disabled and account.role == acc.ROLE_PLAYER
        and not account.is_default_local
    )
    if usable and hasher.verify(body.password, account.password_hash):
        limiter.reset(ident)
        if hasher.needs_rehash(account.password_hash):
            store.set_password(account.player_uuid, hasher.hash(body.password))
        token, session = store.create_session(account.player_uuid)  # fresh token on login (rotation)
        _set_cookie(response, token)
        return _account_view(account, session)
    if not usable:
        hasher.dummy_verify(body.password)
    limiter.record(source, ident)
    raise HTTPException(401, {"code": "invalid_credentials"})


@router.post("/logout", status_code=204)
def logout(response: Response, ctx: AuthContext = Depends(current_account),
           store: acc.AccountStore = Depends(get_account_store)) -> None:
    store.revoke_session(ctx.token)
    response.delete_cookie(session_cookie_name(), path="/")
    if ctx.account.is_default_local:
        response.set_cookie(LOCALUSER_OPT_OUT_COOKIE, "1", httponly=True, samesite="lax", path="/")


class RecoverBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(max_length=config.ACCOUNT_NAME_MAX_LENGTH * 4)
    recovery_token: str = Field(max_length=256)
    new_password: str = Field(max_length=config.PASSWORD_MAX_LENGTH + 1)


@router.post("/recover", status_code=204)
def recover_password(
    body: RecoverBody, request: Request, response: Response,
    store: acc.AccountStore = Depends(get_account_store),
    hasher: PasswordHasher = Depends(get_password_hasher),
    limiter: FailureLimiter = Depends(get_login_limiter),
) -> None:
    """Redeem an OS-operator recovery credential (plan section 6): replaces the password only.

    Revokes every session and never signs in; unknown name, wrong credential, used or expired
    all fail alike. Throttled like a login."""
    _no_store(response)
    source = f"src:{_source(request)}"
    ident = f"name:{acc.normalize_name(body.name)}"
    if limiter.retry_after(source, ident):
        raise HTTPException(429, {"code": "rate_limited"})
    problem = policy.check(body.new_password, name=body.name)
    if problem is not None:
        raise HTTPException(400, {"code": f"password_{problem}"})
    if not store.redeem_recovery(body.name, body.recovery_token, hasher.hash(body.new_password), acc.ROLE_PLAYER):
        limiter.record(source, ident)
        raise HTTPException(400, {"code": "invalid_recovery"})
    store.record_audit(body.name, "recovery.redeemed", "role:player")


@router.get("/sessions")
def list_sessions(
    response: Response, ctx: AuthContext = Depends(current_account),
    store: acc.AccountStore = Depends(get_account_store),
) -> list[dict]:
    """The caller's own live sessions; `current` marks the one making this request."""
    _no_store(response)
    current = acc._digest(ctx.token)[:acc.SESSION_ID_LENGTH]
    return [
        {"id": s["id"], "created_at": s["created_at"], "last_seen": s["last_seen"],
         "expires_at": s["expires_at"], "current": s["id"] == current}
        for s in store.list_sessions(ctx.account.player_uuid)
    ]


@router.delete("/sessions/{session_id}", status_code=204)
def revoke_session(
    session_id: str, ctx: AuthContext = Depends(current_account),
    store: acc.AccountStore = Depends(get_account_store),
) -> None:
    if not store.revoke_session_by_id(ctx.account.player_uuid, session_id):
        raise HTTPException(404, {"code": "not_found"})


@router.post("/logout-all", status_code=204)
def logout_all(response: Response, ctx: AuthContext = Depends(current_account),
               store: acc.AccountStore = Depends(get_account_store)) -> None:
    store.revoke_all_sessions(ctx.account.player_uuid)
    response.delete_cookie(session_cookie_name(), path="/")


@router.post("/password-change", status_code=204)
def password_change(
    body: PasswordChangeBody, request: Request, ctx: AuthContext = Depends(current_account),
    store: acc.AccountStore = Depends(get_account_store),
    hasher: PasswordHasher = Depends(get_password_hasher),
    limiter: FailureLimiter = Depends(get_login_limiter),
) -> None:
    ident = f"name:{acc.normalize_name(ctx.account.name)}"
    if limiter.retry_after(ident):
        raise HTTPException(429, {"code": "rate_limited"})
    if not hasher.verify(body.current_password, ctx.account.password_hash):
        limiter.record(ident)
        raise HTTPException(401, {"code": "invalid_credentials"})
    problem = policy.check(body.new_password, name=ctx.account.name)
    if problem is not None:
        raise HTTPException(400, {"code": f"password_{problem}"})
    # Revokes every other session; the current one stays signed in (plan §3).
    store.set_password(ctx.account.player_uuid, hasher.hash(body.new_password), keep_session=ctx.token)


@router.post("/invitations", status_code=201)
def create_invitation(
    response: Response, ctx: AuthContext = Depends(current_account),
    store: acc.AccountStore = Depends(get_account_store),
) -> dict:
    """Players mint `player` invitations only (admin tokens are an admin-only route, PLR-9d)."""
    _no_store(response)
    try:
        token = store.create_invitation(ctx.account.player_uuid, acc.ROLE_PLAYER)
    except acc.InvitationLimitError:
        raise HTTPException(429, {"code": "invitation_limit"})
    # The raw token is shown exactly once; only its digest is stored.
    return {"token": token, "expires_in_seconds": int(config.INVITE_TTL_SECONDS)}


@router.get("/invitations")
def list_invitations(
    response: Response, ctx: AuthContext = Depends(current_account),
    store: acc.AccountStore = Depends(get_account_store),
) -> list[dict]:
    _no_store(response)
    return store.list_invitations(ctx.account.player_uuid)


@router.delete("/invitations/{invitation_id}", status_code=204)
def revoke_invitation(
    invitation_id: str, ctx: AuthContext = Depends(current_account),
    store: acc.AccountStore = Depends(get_account_store),
) -> None:
    if not store.revoke_invitation(invitation_id, by=ctx.account.player_uuid, is_admin=False):
        raise HTTPException(404, {"code": "not_found"})
