"""Administration API, `/api/admin` (PLR-9d, plan section 6).

Per-request authentication, no admin session and no admin cookie (`api/admin_auth.py`); TOTP MFA
(required in `--online`, optional and enforced once enrolled elsewhere). Admins
manage player accounts (list, disable, re-enable, revoke sessions, delete with a counts-only
preview), invitations (player and admin tokens), the **global** decks, the allowlisted
database-update jobs and read the audit log. They cannot read private decks or assets, play,
control bot/MCP seats, reset a password or change a role (OS-operator tasks).

Every mutation is audited (actor, action, target, result; never credentials or private
content). Deleting a player needs the account's exact name as confirmation after a counts-only preview;
deleting a global deck needs none (the /admin UI asks one plain yes/no question, VIS-22).
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from mtg_analyzer import config
from mtg_analyzer.api.admin_auth import (
    MFA_VIA_OTP, MFA_VIA_RECOVERY, NO_STORE, admin_login, client_key, deny, get_admin_grants, get_admin_limiter,
    is_remote, require_admin, require_local_surface, require_setup_admin,
)
from mtg_analyzer.api.auth import get_password_hasher, get_signup_limiter
from mtg_analyzer.api.dependencies import (
    get_account_store, get_admin_jobs, get_deck_database, get_game_session_manager, get_player_asset_store,
)
from mtg_analyzer.models.decks.deck import Deck
from mtg_analyzer.services import account_store as acc
from mtg_analyzer.services import admin_service
from mtg_analyzer.services import password_policy as policy
from mtg_analyzer.services import totp
from mtg_analyzer.services.admin_grants import AdminGrants, binding_for
from mtg_analyzer.services.admin_jobs import JOB_KINDS, AdminJobs, JobAlreadyRunning, UnknownJobKind
from mtg_analyzer.services.deck_database import DeckDatabase
from mtg_analyzer.services.game_session import GameSessionManager
from mtg_analyzer.services.password_hasher import PasswordHasher
from mtg_analyzer.services.player_assets import PlayerAssetStore
from mtg_analyzer.services.rate_limiter import FailureLimiter


def _no_store(response: Response) -> None:
    for key, value in NO_STORE.items():
        response.headers[key] = value


router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(_no_store)])

#: Admin names are carried in a Basic header (`name:password`), so they cannot contain the separator.
BASIC_SEPARATOR = ":"


def _target_name(name: str) -> str:
    return f"player:{name}"


# ---------------------------------------------------------------------------
# State, setup, signup
# ---------------------------------------------------------------------------

@router.get("/state", dependencies=[Depends(require_local_surface)])
def state(request: Request, store: acc.AccountStore = Depends(get_account_store)) -> dict:
    """What the page needs before anyone has typed a password (local requests only)."""
    return {
        "setup_open": store.setup_open(),
        "has_admin": store.count_accounts(acc.ROLE_ADMIN) > 0,
        "run_mode": config.RUN_MODE,
        "admin_password_min_length": config.ADMIN_PASSWORD_MIN_LENGTH,
        "mfa_required": config.RUN_MODE == "online",
        # PLR-19: whether THIS connection must present a code (only remote ones; local = password only).
        "second_factor_required": is_remote(request),
        "mfa_digits": config.TOTP_DIGITS,
    }


class SetupBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    new_password: str = Field(max_length=config.PASSWORD_MAX_LENGTH + 1)


@router.post("/setup")
def complete_setup(
    body: SetupBody,
    account: acc.Account = Depends(require_setup_admin),
    store: acc.AccountStore = Depends(get_account_store),
    hasher: PasswordHasher = Depends(get_password_hasher),
) -> dict:
    """Initial setup (plan section 6): a new admin password, then the first invitations.

    Authenticated with the seeded credential (`setup_required` only). The initial password is
    not reusable and the 15-character admin policy applies. The flag clears in one conditional
    UPDATE; the response carries one admin and one player invitation, shown once."""
    problem = policy.check(body.new_password, admin=True, name=account.name)
    if problem is None and (
        body.new_password == acc.INITIAL_ADMIN_PASSWORD or hasher.verify(body.new_password, account.password_hash)
    ):
        problem = "reused_initial"
    if problem is not None:
        raise HTTPException(400, {"code": f"password_{problem}"}, headers=NO_STORE)
    if not store.complete_setup(account.player_uuid, hasher.hash(body.new_password)):
        raise deny(409, "setup_not_open")
    store.record_audit(account.name, "admin.setup_completed")
    tokens = {
        role: store.create_invitation(account.player_uuid, role, enforce_limits=False)
        for role in (acc.ROLE_ADMIN, acc.ROLE_PLAYER)
    }
    store.record_audit(account.name, "invitation.created", "role:admin,player (setup)")
    return {"invitations": tokens, "expires_in_seconds": int(config.INVITE_TTL_SECONDS)}


class AdminSignupBody(BaseModel):
    model_config = ConfigDict(extra="forbid")  # a client never submits a role
    name: str = Field(max_length=config.ACCOUNT_NAME_MAX_LENGTH * 4)
    password: str = Field(max_length=config.PASSWORD_MAX_LENGTH + 1)
    invitation: str = Field(max_length=256)


@router.post("/signup", status_code=201, dependencies=[Depends(require_local_surface)])
def admin_signup(
    body: AdminSignupBody, request: Request,
    store: acc.AccountStore = Depends(get_account_store),
    hasher: PasswordHasher = Depends(get_password_hasher),
    limiter: FailureLimiter = Depends(get_signup_limiter),
) -> dict:
    """Redeem an **admin** invitation (never the player signup, plan section 6).

    Creates no session: the new admin signs in per request like every admin. In `--online` the
    account exists but stays inactive until an authenticator is enrolled (`require_admin` refuses
    everything but the enrolment routes with `mfa_enrollment_required`)."""
    source = f"admin-signup:{request.client.host if request.client else 'unknown'}"
    wait = limiter.retry_after(source)
    if wait:
        raise deny(429, "rate_limited", **{"Retry-After": str(int(wait) + 1)})
    problem = policy.check(body.password, admin=True, name=body.name)
    if problem is not None:
        raise HTTPException(400, {"code": f"password_{problem}"}, headers=NO_STORE)
    try:
        acc.validate_name(body.name)
        if BASIC_SEPARATOR in body.name:
            raise acc.InvalidNameError("characters")
    except acc.InvalidNameError as exc:
        raise HTTPException(400, {"code": exc.code}, headers=NO_STORE)
    limiter.record(source)
    try:
        account = store.create_account_with_invitation(body.name, hasher.hash(body.password), body.invitation, acc.ROLE_ADMIN)
    except acc.NameTakenError:
        raise HTTPException(409, {"code": "name_taken"}, headers=NO_STORE)
    except acc.InvalidInvitationError:
        raise HTTPException(400, {"code": "invalid_invitation"}, headers=NO_STORE)
    store.record_audit(account.name, "admin.signup")
    # PLR-19: a locally signed-up admin works at once; the authenticator is due before the first REMOTE use.
    return {
        "name": account.name,
        "mfa_enrollment_required": config.RUN_MODE == "online" and is_remote(request),
        "mfa_enrollment_required_for_remote": config.RUN_MODE == "online",
    }


class RecoverBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(max_length=config.ACCOUNT_NAME_MAX_LENGTH * 4)
    recovery_token: str = Field(max_length=256)
    new_password: str = Field(max_length=config.PASSWORD_MAX_LENGTH + 1)


@router.post("/recover", status_code=204, dependencies=[Depends(require_local_surface)])
def admin_recover(
    body: RecoverBody, request: Request,
    store: acc.AccountStore = Depends(get_account_store),
    hasher: PasswordHasher = Depends(get_password_hasher),
    limiter: FailureLimiter = Depends(get_admin_limiter),
) -> None:
    """Redeem an OS-operator recovery credential for an admin (replaces the password, no login)."""
    ident = f"admin:{acc.normalize_name(body.name)}"
    wait = limiter.retry_after(ident)
    if wait:
        raise deny(429, "rate_limited", **{"Retry-After": str(int(wait) + 1)})
    problem = policy.check(body.new_password, admin=True, name=body.name)
    if problem is not None:
        raise HTTPException(400, {"code": f"password_{problem}"}, headers=NO_STORE)
    if not store.redeem_recovery(body.name, body.recovery_token, hasher.hash(body.new_password), acc.ROLE_ADMIN):
        limiter.record(ident)
        raise HTTPException(400, {"code": "invalid_recovery"}, headers=NO_STORE)
    store.record_audit(body.name, "recovery.redeemed", "role:admin")


# ---------------------------------------------------------------------------
# Authenticated admin
# ---------------------------------------------------------------------------

@router.get("/whoami")
def whoami(admin: acc.Account = Depends(require_admin), store: acc.AccountStore = Depends(get_account_store)) -> dict:
    mfa = store.get_mfa(admin.player_uuid)
    return {"name": admin.name, "mfa_enrolled": mfa.enrolled, "mfa_required": config.RUN_MODE == "online"}


# -- MFA (TOTP + single-use recovery codes) ------------------------------------------------------

def _enrollable_admin(account: acc.Account = Depends(admin_login)) -> acc.Account:
    """An authenticated admin who finished initial setup; the one dependency the MFA routes use
    (they must work for an `--online` admin who has no authenticator yet)."""
    if account.setup_required:
        raise deny(403, "setup_required")
    return account


def _limit_key(admin: acc.Account) -> str:
    return f"admin:{acc.normalize_name(admin.name)}"


def _bad_code(store: acc.AccountStore, limiter: FailureLimiter, admin: acc.Account, action: str) -> HTTPException:
    limiter.record(_limit_key(admin))
    store.record_audit(admin.name, action, result="denied (code)")
    return HTTPException(400, {"code": "invalid_code"}, headers=NO_STORE)


def _verify_current(
    store: acc.AccountStore, limiter: FailureLimiter, admin: acc.Account, code: Optional[str], action: str
) -> None:
    """Fresh proof of the authenticator for a sensitive MFA change: a current code or a recovery code.

    The code goes through the same replay protection as a login. A code already spent on this very
    request (`X-Admin-OTP`) cannot be spent again, so send the grant header and the code in the body."""
    if not code:
        raise HTTPException(400, {"code": "current_code_required"}, headers=NO_STORE)
    if store.consume_second_factor(admin.player_uuid, code[: config.ACCOUNT_NAME_MAX_LENGTH * 4]) is None:
        raise _bad_code(store, limiter, admin, action)


def _new_grant(request: Request, store: acc.AccountStore, grants: AdminGrants, admin: acc.Account) -> dict:
    """A fresh grant bound to the admin's *current* credential state (call after any MFA change)."""
    account = store.get(admin.player_uuid) or admin
    binding = binding_for(account.password_hash, store.get_mfa(admin.player_uuid).version)
    token = grants.issue(admin.player_uuid, client_key(request), binding)
    return {"grant": token, "grant_idle_seconds": int(config.ADMIN_GRANT_IDLE_SECONDS)}


@router.get("/mfa")
def mfa_status(admin: acc.Account = Depends(_enrollable_admin), store: acc.AccountStore = Depends(get_account_store)) -> dict:
    mfa = store.get_mfa(admin.player_uuid)
    return {"enrolled": mfa.enrolled, "pending": mfa.pending, "recovery_codes_left": mfa.recovery_codes_left,
            "required": config.RUN_MODE == "online"}


class EnrollBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current: Optional[str] = Field(default=None, max_length=config.ACCOUNT_NAME_MAX_LENGTH * 4)


@router.post("/mfa/enroll")
def mfa_enroll(
    body: EnrollBody, admin: acc.Account = Depends(_enrollable_admin),
    store: acc.AccountStore = Depends(get_account_store), limiter: FailureLimiter = Depends(get_admin_limiter),
) -> dict:
    """Start enrolment (or replacement): the request already proved the password; a replacement also
    needs a current authenticator or recovery code. Returns the new secret and the `otpauth://` URI as
    text; nothing changes until `/mfa/confirm` succeeds with a code from the new secret."""
    replacing = store.get_mfa(admin.player_uuid).enrolled
    if replacing:
        _verify_current(store, limiter, admin, body.current, "mfa.replace_denied")
    secret = totp.new_secret()
    store.begin_mfa_enrollment(admin.player_uuid, secret)
    store.record_audit(admin.name, "mfa.replacement_started" if replacing else "mfa.enrollment_started")
    return {"secret": secret, "otpauth_uri": totp.provisioning_uri(secret, admin.name), "replacing": replacing,
            "digits": config.TOTP_DIGITS, "period_seconds": config.TOTP_PERIOD_SECONDS}


class ConfirmCodeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(max_length=config.ACCOUNT_NAME_MAX_LENGTH * 4)


@router.post("/mfa/confirm")
def mfa_confirm(
    body: ConfirmCodeBody, request: Request, admin: acc.Account = Depends(_enrollable_admin),
    store: acc.AccountStore = Depends(get_account_store), limiter: FailureLimiter = Depends(get_admin_limiter),
    grants: AdminGrants = Depends(get_admin_grants),
) -> dict:
    """Finish enrolment with one valid code of the pending secret. The recovery codes are shown
    once; the response also carries a grant so the page continues without waiting a time step."""
    replacing = store.get_mfa(admin.player_uuid).enrolled
    recovery_codes = store.confirm_mfa_enrollment(admin.player_uuid, body.code)
    if recovery_codes is None:
        raise _bad_code(store, limiter, admin, "mfa.confirm_denied")
    grants.revoke_all(admin.player_uuid)  # earlier grants ended with the old secret
    store.record_audit(admin.name, "mfa.replaced" if replacing else "mfa.enrolled")
    return {"recovery_codes": recovery_codes, **_new_grant(request, store, grants, admin)}


@router.post("/mfa/grant")
def mfa_grant(
    request: Request, admin: acc.Account = Depends(require_admin),
    store: acc.AccountStore = Depends(get_account_store), grants: AdminGrants = Depends(get_admin_grants),
) -> dict:
    """Trade this request's verified code (`X-Admin-OTP`) for a grant the page reuses (see `admin_grants`)."""
    if getattr(request.state, "admin_mfa", None) not in (MFA_VIA_OTP, MFA_VIA_RECOVERY):
        raise HTTPException(400, {"code": "otp_required"}, headers=NO_STORE)
    store.record_audit(admin.name, "admin.grant_issued")
    return _new_grant(request, store, grants, admin)


@router.post("/mfa/recovery-codes")
def mfa_new_recovery_codes(
    body: EnrollBody, request: Request, admin: acc.Account = Depends(require_admin),
    store: acc.AccountStore = Depends(get_account_store), limiter: FailureLimiter = Depends(get_admin_limiter),
    grants: AdminGrants = Depends(get_admin_grants),
) -> dict:
    """Replace all recovery codes (current authenticator or recovery code required); shown once."""
    _verify_current(store, limiter, admin, body.current, "mfa.recovery_codes_denied")
    codes = store.regenerate_recovery_codes(admin.player_uuid)
    if codes is None:
        raise HTTPException(409, {"code": "mfa_not_enrolled"}, headers=NO_STORE)
    grants.revoke_all(admin.player_uuid)
    store.record_audit(admin.name, "mfa.recovery_codes_regenerated")
    return {"recovery_codes": codes, **_new_grant(request, store, grants, admin)}


@router.post("/mfa/disable", status_code=204)
def mfa_disable(
    body: EnrollBody, admin: acc.Account = Depends(require_admin),
    store: acc.AccountStore = Depends(get_account_store), limiter: FailureLimiter = Depends(get_admin_limiter),
    grants: AdminGrants = Depends(get_admin_grants),
) -> None:
    """Turn the optional MFA of a LAN/localdev admin off. Never in `--online`, where it is mandatory."""
    if config.RUN_MODE == "online":
        raise HTTPException(409, {"code": "mfa_required"}, headers=NO_STORE)
    _verify_current(store, limiter, admin, body.current, "mfa.disable_denied")
    store.clear_mfa(admin.player_uuid)
    grants.revoke_all(admin.player_uuid)
    store.record_audit(admin.name, "mfa.disabled")


class PasswordChangeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    new_password: str = Field(max_length=config.PASSWORD_MAX_LENGTH + 1)


@router.post("/password-change", status_code=204)
def password_change(
    body: PasswordChangeBody,
    admin: acc.Account = Depends(require_admin),
    store: acc.AccountStore = Depends(get_account_store),
    hasher: PasswordHasher = Depends(get_password_hasher),
) -> None:
    """The admin changes their own password (the request itself proved the current one)."""
    problem = policy.check(body.new_password, admin=True, name=admin.name)
    if problem is not None:
        raise HTTPException(400, {"code": f"password_{problem}"}, headers=NO_STORE)
    store.set_password(admin.player_uuid, hasher.hash(body.new_password))
    store.record_audit(admin.name, "admin.password_changed")


# -- players ------------------------------------------------------------------

def _player_or_404(store: acc.AccountStore, player_uuid: str) -> acc.Account:
    account = admin_service.managed_player(store, player_uuid)
    if account is None:
        raise HTTPException(404, {"code": "not_found"}, headers=NO_STORE)
    return account


def _page(limit: int, offset: int) -> tuple[int, int]:
    return max(1, min(limit, config.ADMIN_PAGE_MAX)), max(0, offset)


@router.get("/players")
def list_players(
    q: str = "", limit: int = config.ADMIN_PAGE_MAX, offset: int = 0,
    admin: acc.Account = Depends(require_admin), store: acc.AccountStore = Depends(get_account_store),
) -> dict:
    limit, offset = _page(limit, offset)
    players, total = store.list_players(q[: config.ACCOUNT_NAME_MAX_LENGTH * 4], limit=limit, offset=offset)
    return {"players": players, "total": total}


@router.get("/pending-deletions")
def pending_deletions(
    admin: acc.Account = Depends(require_admin), store: acc.AccountStore = Depends(get_account_store),
) -> dict:
    """Self-requested deletions in their grace period, with the due date (`MTG_ACCOUNT_DELETION_GRACE_DAYS`)."""
    return {"pending": store.list_pending_deletions(), "grace_days": config.ACCOUNT_DELETION_GRACE_SECONDS / 86400}


@router.post("/players/{player_uuid}/disable", status_code=204)
def disable_player(
    player_uuid: str, admin: acc.Account = Depends(require_admin),
    store: acc.AccountStore = Depends(get_account_store),
) -> None:
    """Blocks login and ends every session now (REST at once, sockets at the next sweep); data stays."""
    account = _player_or_404(store, player_uuid)
    if account.is_default_local:
        raise HTTPException(409, {"code": "protected_account"}, headers=NO_STORE)
    store.set_disabled(account.player_uuid, True)
    store.record_audit(admin.name, "player.disabled", _target_name(account.name))


@router.post("/players/{player_uuid}/enable", status_code=204)
def enable_player(
    player_uuid: str, admin: acc.Account = Depends(require_admin),
    store: acc.AccountStore = Depends(get_account_store),
) -> None:
    account = _player_or_404(store, player_uuid)
    if store.cancel_deletion(account.player_uuid):
        # Re-enabling within the grace period withdraws the player's own deletion request.
        store.record_audit(admin.name, "player.deletion_cancelled", _target_name(account.name))
        return
    store.set_disabled(account.player_uuid, False)
    store.record_audit(admin.name, "player.enabled", _target_name(account.name))


@router.post("/players/{player_uuid}/revoke-sessions", status_code=204)
def revoke_player_sessions(
    player_uuid: str, admin: acc.Account = Depends(require_admin),
    store: acc.AccountStore = Depends(get_account_store),
) -> None:
    account = _player_or_404(store, player_uuid)
    store.revoke_all_sessions(account.player_uuid)
    store.record_audit(admin.name, "player.sessions_revoked", _target_name(account.name))


@router.get("/players/{player_uuid}/delete-preview")
def player_delete_preview(
    player_uuid: str, admin: acc.Account = Depends(require_admin),
    store: acc.AccountStore = Depends(get_account_store),
    decks: DeckDatabase = Depends(get_deck_database),
    assets: PlayerAssetStore = Depends(get_player_asset_store),
) -> dict:
    """Counts only (decks, assets, sessions): the admin never sees private content."""
    account = _player_or_404(store, player_uuid)
    preview = admin_service.delete_preview(store, decks, assets, account).counts()
    preview["deletable"] = not account.is_default_local
    preview["tombstone_days"] = config.NAME_TOMBSTONE_SECONDS / 86400
    return preview


class ConfirmBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm_name: str = Field(max_length=config.ADMIN_DECK_TEXT_MAX)


@router.post("/players/{player_uuid}/delete")
def delete_player(
    player_uuid: str, body: ConfirmBody, admin: acc.Account = Depends(require_admin),
    store: acc.AccountStore = Depends(get_account_store),
    decks: DeckDatabase = Depends(get_deck_database),
    assets: PlayerAssetStore = Depends(get_player_asset_store),
    game_sessions: GameSessionManager = Depends(get_game_session_manager),
) -> dict:
    """Cascade delete after the preview; the exact name is the confirmation."""
    account = _player_or_404(store, player_uuid)
    if account.is_default_local:
        raise HTTPException(409, {"code": "protected_account"}, headers=NO_STORE)
    if body.confirm_name != account.name:
        raise HTTPException(400, {"code": "confirmation_mismatch"}, headers=NO_STORE)
    removed = admin_service.delete_player(store, decks, assets, game_sessions, account)
    store.record_audit(admin.name, "player.deleted", _target_name(account.name))
    return removed.counts()


# -- invitations ------------------------------------------------------------------

class InvitationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: str = acc.ROLE_PLAYER


@router.get("/invitations")
def list_invitations(
    admin: acc.Account = Depends(require_admin), store: acc.AccountStore = Depends(get_account_store),
) -> list[dict]:
    """Metadata only: an issued token can never be read again."""
    return store.list_invitations()


@router.post("/invitations", status_code=201)
def create_invitation(
    body: InvitationBody, admin: acc.Account = Depends(require_admin),
    store: acc.AccountStore = Depends(get_account_store),
) -> dict:
    if body.role not in (acc.ROLE_PLAYER, acc.ROLE_ADMIN):
        raise HTTPException(422, {"code": "invalid_role"}, headers=NO_STORE)
    token = store.create_invitation(admin.player_uuid, body.role, enforce_limits=False)
    store.record_audit(admin.name, "invitation.created", f"role:{body.role}")
    return {"token": token, "role": body.role, "expires_in_seconds": int(config.INVITE_TTL_SECONDS)}


@router.delete("/invitations/{invitation_id}", status_code=204)
def revoke_invitation(
    invitation_id: str, admin: acc.Account = Depends(require_admin),
    store: acc.AccountStore = Depends(get_account_store),
) -> None:
    if not store.revoke_invitation(invitation_id, by=admin.player_uuid, is_admin=True):
        raise HTTPException(404, {"code": "not_found"}, headers=NO_STORE)
    store.record_audit(admin.name, "invitation.revoked", f"id:{invitation_id[:acc.INVITATION_ID_LENGTH]}")


# -- global decks -------------------------------------------------------------------

class GlobalDeckBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(default="", max_length=config.ADMIN_DECK_TEXT_MAX)
    commander_text: str = Field(default="", alias="commanderText", max_length=config.ADMIN_DECK_TEXT_MAX)
    mainboard_text: str = Field(default="", alias="mainboardText", max_length=config.ADMIN_DECK_TEXT_MAX)
    sideboard_text: str = Field(default="", alias="sideboardText", max_length=config.ADMIN_DECK_TEXT_MAX)
    author: Optional[str] = Field(default=None, max_length=config.ACCOUNT_NAME_MAX_LENGTH * 4)
    is_cube: bool = Field(default=False, alias="isCube")


def _deck_summary(deck: Deck) -> dict:
    return {"id": deck.id, "name": deck.name, "author": deck.author, "created_at": deck.created_at,
            "is_cube": deck.is_cube}


def _deck_detail(deck: Deck) -> dict:
    return {**_deck_summary(deck), "commanderText": deck.commander_text, "mainboardText": deck.mainboard_text,
            "sideboardText": deck.sideboard_text}


def _global_deck_or_404(decks: DeckDatabase, deck_id: str) -> Deck:
    deck = decks.get_global(deck_id)
    if deck is None:
        raise HTTPException(404, {"code": "not_found"}, headers=NO_STORE)
    return deck


@router.get("/decks")
def list_global_decks(
    admin: acc.Account = Depends(require_admin), decks: DeckDatabase = Depends(get_deck_database),
) -> list[dict]:
    return [_deck_summary(d) for d in decks.list_global()]


@router.post("/decks", status_code=201)
def create_global_deck(
    body: GlobalDeckBody, admin: acc.Account = Depends(require_admin),
    decks: DeckDatabase = Depends(get_deck_database), store: acc.AccountStore = Depends(get_account_store),
) -> dict:
    deck = Deck(
        name=body.name, commander_text=body.commander_text, mainboard_text=body.mainboard_text,
        sideboard_text=body.sideboard_text, author=body.author, is_cube=body.is_cube,
    )
    if not decks.save_global(deck):  # a fresh uuid cannot collide; defensive
        raise HTTPException(409, {"code": "conflict"}, headers=NO_STORE)
    store.record_audit(admin.name, "deck.created", f"deck:{deck.id}")
    return _deck_detail(deck)


@router.get("/decks/{deck_id}")
def get_global_deck(
    deck_id: str, admin: acc.Account = Depends(require_admin), decks: DeckDatabase = Depends(get_deck_database),
) -> dict:
    return _deck_detail(_global_deck_or_404(decks, deck_id))


@router.put("/decks/{deck_id}")
def update_global_deck(
    deck_id: str, body: GlobalDeckBody, admin: acc.Account = Depends(require_admin),
    decks: DeckDatabase = Depends(get_deck_database), store: acc.AccountStore = Depends(get_account_store),
) -> dict:
    existing = _global_deck_or_404(decks, deck_id)
    text_changed = (existing.commander_text, existing.mainboard_text, existing.sideboard_text) != (
        body.commander_text, body.mainboard_text, body.sideboard_text)
    deck = Deck(
        id=existing.id, name=body.name, commander_text=body.commander_text, mainboard_text=body.mainboard_text,
        sideboard_text=body.sideboard_text, created_at=existing.created_at, sleeve_id=existing.sleeve_id,
        author=body.author, is_cube=body.is_cube, archetypes=existing.archetypes,
        favorite_cards=existing.favorite_cards,
        # Derived caches are recomputed on the next read when the list (or the cube flag) changed.
        color_identity=None if text_changed else existing.color_identity,
        commanders=None if text_changed else existing.commanders,
        validation_result=None if text_changed or existing.is_cube != body.is_cube else existing.validation_result,
        unmodeled_coverage=None if text_changed else existing.unmodeled_coverage,
        unmodeled_coverage_version=None if text_changed else existing.unmodeled_coverage_version,
    )
    if not decks.save_global(deck):
        raise HTTPException(404, {"code": "not_found"}, headers=NO_STORE)
    store.record_audit(admin.name, "deck.updated", f"deck:{deck.id}")
    return _deck_detail(deck)


@router.get("/decks/{deck_id}/delete-preview")
def global_deck_delete_preview(
    deck_id: str, admin: acc.Account = Depends(require_admin), decks: DeckDatabase = Depends(get_deck_database),
) -> dict:
    deck = _global_deck_or_404(decks, deck_id)
    lines = lambda text: sum(1 for line in text.splitlines() if line.strip())  # noqa: E731
    return {"name": deck.name, "lines": lines(deck.commander_text) + lines(deck.mainboard_text)
            + lines(deck.sideboard_text), "author": deck.author, "created_at": deck.created_at}


class DeckDeleteBody(BaseModel):
    """Optional body: a global deck needs no typed confirmation (VIS-22). Unknown fields (a stale client's
    `confirm_name`) are ignored rather than rejected, so an old /admin page keeps working."""
    model_config = ConfigDict(extra="ignore")


@router.post("/decks/{deck_id}/delete")
def delete_global_deck(
    deck_id: str, body: Optional[DeckDeleteBody] = None, admin: acc.Account = Depends(require_admin),
    decks: DeckDatabase = Depends(get_deck_database), store: acc.AccountStore = Depends(get_account_store),
) -> dict:
    deck = _global_deck_or_404(decks, deck_id)
    decks.delete_global(deck.id)
    store.record_audit(admin.name, "deck.deleted", f"deck:{deck.id}")
    return {"deleted": True}


# -- update jobs ------------------------------------------------------------------

class JobBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str = Field(max_length=64)


@router.get("/jobs")
def list_jobs(admin: acc.Account = Depends(require_admin), jobs: AdminJobs = Depends(get_admin_jobs)) -> dict:
    return {"kinds": list(JOB_KINDS), "jobs": jobs.list()}


@router.post("/jobs", status_code=202)
def start_job(
    body: JobBody, admin: acc.Account = Depends(require_admin),
    jobs: AdminJobs = Depends(get_admin_jobs), store: acc.AccountStore = Depends(get_account_store),
) -> dict:
    """Start an allowlisted update; the response holds the job-bound poll token, shown once."""
    try:
        job, token = jobs.start(
            body.kind, admin.name,
            on_finish=lambda j: store.record_audit(admin.name, "job.finished", f"job:{j.kind}", j.state),
        )
    except UnknownJobKind:
        raise HTTPException(422, {"code": "unknown_job_kind"}, headers=NO_STORE)
    except JobAlreadyRunning:
        raise HTTPException(409, {"code": "job_running"}, headers=NO_STORE)
    store.record_audit(admin.name, "job.started", f"job:{job.kind}")
    return {"job": job.view(), "poll_token": token}


@router.get("/jobs/{job_id}", dependencies=[Depends(require_local_surface)])
def get_job(
    job_id: str, request: Request,
    x_job_token: Optional[str] = Header(default=None),
    jobs: AdminJobs = Depends(get_admin_jobs),
    store: acc.AccountStore = Depends(get_account_store),
    hasher: PasswordHasher = Depends(get_password_hasher),
    limiter: FailureLimiter = Depends(get_admin_limiter),
    grants: AdminGrants = Depends(get_admin_grants),
) -> dict:
    """One job's progress: with its poll token (no password) or with admin credentials."""
    if x_job_token:
        view = jobs.get_with_token(job_id, x_job_token)
        if view is None:
            raise HTTPException(404, {"code": "not_found"}, headers=NO_STORE)
        return view
    require_admin(request, admin_login(request, store, hasher, limiter, grants), store)
    view = jobs.get(job_id)
    if view is None:
        raise HTTPException(404, {"code": "not_found"}, headers=NO_STORE)
    return view


# -- audit log ---------------------------------------------------------------------

@router.get("/audit")
def audit_log(
    limit: int = config.ADMIN_PAGE_MAX, offset: int = 0,
    admin: acc.Account = Depends(require_admin), store: acc.AccountStore = Depends(get_account_store),
) -> dict:
    limit, offset = _page(limit, offset)
    entries, total = store.list_audit(limit=limit, offset=offset)
    return {"entries": entries, "total": total}
