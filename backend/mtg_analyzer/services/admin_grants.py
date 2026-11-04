"""Short-lived, server-held, request-bound admin MFA grants (PLR-9d, plan section 6).

An authenticator code is valid for one 30 second step and each step is accepted once, so a page
that makes many requests cannot present a fresh code on every one. After one request verified
password and code (`POST /api/admin/mfa/grant`) the server hands out a **grant**: an opaque
256-bit token, kept only as a digest in memory, bound to

* the admin (`player_uuid`),
* the client address the request came from, and
* a *binding* string the caller derives from the admin's credential state (password hash and MFA
  version), so a password change, an MFA change or an operator reset kills every grant.

The grant never replaces the password: every admin request still carries the Basic credentials
and the grant in `X-Admin-Grant`. It is not a cookie and not ambient (a forged cross-site request
cannot attach it), expires after an idle and an absolute limit, and is gone after a restart.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Callable

from mtg_analyzer import config

#: Bytes of entropy in a grant token (256 bits).
GRANT_TOKEN_BYTES = 32


@dataclass
class _Grant:
    player_uuid: str
    peer: str
    binding: str
    created_at: float
    last_used: float


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class AdminGrants:
    def __init__(self, *, clock: Callable[[], float] = time.time) -> None:
        self._now = clock
        self._lock = threading.Lock()
        self._grants: dict[str, _Grant] = {}

    def issue(self, player_uuid: str, peer: str, binding: str) -> str:
        """Create a grant (the raw token is returned once); the admin's oldest grants are evicted past the cap."""
        token = secrets.token_urlsafe(GRANT_TOKEN_BYTES)
        now = self._now()
        with self._lock:
            self._expire(now)
            mine = sorted((g.created_at, d) for d, g in self._grants.items() if g.player_uuid == player_uuid)
            for _, digest in mine[: max(0, len(mine) - config.ADMIN_GRANT_MAX_PER_ADMIN + 1)]:
                del self._grants[digest]
            self._grants[_digest(token)] = _Grant(player_uuid, peer, binding, now, now)
        return token

    def check(self, token: str, player_uuid: str, peer: str, binding: str) -> bool:
        """Whether ``token`` is a live grant of this admin from this address and credential state; slides the idle window."""
        if not token:
            return False
        now = self._now()
        with self._lock:
            self._expire(now)
            grant = self._grants.get(_digest(token))
            if grant is None:
                return False
            ok = (
                hmac.compare_digest(grant.player_uuid, player_uuid)
                and hmac.compare_digest(grant.peer, peer)
                and hmac.compare_digest(grant.binding, binding)
            )
            if ok:
                grant.last_used = now
            return ok

    def revoke_all(self, player_uuid: str) -> None:
        with self._lock:
            for digest in [d for d, g in self._grants.items() if g.player_uuid == player_uuid]:
                del self._grants[digest]

    def _expire(self, now: float) -> None:
        dead = [
            d for d, g in self._grants.items()
            if now - g.last_used > config.ADMIN_GRANT_IDLE_SECONDS
            or now - g.created_at > config.ADMIN_GRANT_ABSOLUTE_SECONDS
        ]
        for digest in dead:
            del self._grants[digest]

    def __len__(self) -> int:
        with self._lock:
            return len(self._grants)


def binding_for(password_hash: str, mfa_version: int) -> str:
    """Credential state a grant is tied to: changes whenever the password or the MFA setup does."""
    return hashlib.sha256(f"{password_hash}|{mfa_version}".encode("utf-8")).hexdigest()

