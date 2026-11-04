"""Who is looking at a global deck or playing a session: an account or an anonymous visitor (PLR-18).

Global decks are open to everyone (plan section 6, user decision 2026-11-04), so the deck
reads and the play routes accept a visitor without a login. What stays login-only: writes,
copies, private decks, favourites, multiplayer, uploads (they keep `current_account`).

Two dependencies, both built on `current_context` so a logged-in caller behaves exactly as
before (including the CSRF check on unsafe methods):

* `viewer`      read-only. Never sets a cookie; an anonymous caller without an anonymous id
                has `owner=None` and so owns no session.
* `play_viewer` for routes that *create* a session or job. An anonymous caller without a valid
                anonymous id is issued one here.

Owner proof of an anonymous visitor: a random id the server issued, in an HttpOnly,
SameSite=Lax cookie (host-only `__Host-` and Secure in `--online`, the profile of the session
cookie, `api/auth.py`). The cookie value is `<random>.<mac>` with a MAC under a per-process
key, so only a value this server issued is accepted (a client-chosen or tampered value is
treated as no id). Server side nothing is stored but the *digest* of the random part, as the
session owner `anon:<digest>`: a leaked session table does not yield a usable cookie. The key
changes on restart, which also drops the in-memory sessions the ids could reach.

CSRF: the account CSRF token (`X-CSRF-Token`) is bound to a server-side login session; an
anonymous visitor has none, and none is needed. The anonymous cookie is SameSite=Lax, so a
browser does not send it on a cross-site POST, `request_guard` refuses a foreign or `null`
Origin and a cross-site `Sec-Fetch-Site` on every unsafe method before a route runs, and
what a forged request could reach with the cookie is the visitor's own throwaway sessions on
public decks. Nothing an anonymous cookie holds is private to the person.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

from fastapi import Depends, HTTPException, Request, Response

from mtg_analyzer import config
from mtg_analyzer.api.auth import AuthContext, current_context
from mtg_analyzer.services.game_session import ANONYMOUS_OWNER_PREFIX

#: Cookie names: host-only `__Host-` needs Secure (online only), as for the session cookie.
ANON_COOKIE_ONLINE = "__Host-mtg_anon"
ANON_COOKIE_LAN = "mtg_anon"

#: Entropy of the anonymous id (bytes before encoding): unguessable like a session token.
ANON_ID_BYTES = 32

#: Shape of a well-formed cookie value (`<urlsafe id>.<hex mac>`); anything else is no id.
_COOKIE_SHAPE = re.compile(r"^[A-Za-z0-9_-]{20,128}\.[0-9a-f]{64}$")

#: Domain separation so the MAC and the owner digest can never be confused.
_MAC_CONTEXT = b"mtg-anon-id-mac"
_OWNER_CONTEXT = b"mtg-anon-id-owner"


@dataclass(frozen=True)
class Viewer:
    """The reader/player behind a request.

    ``player_uuid`` is the verified account, ``None`` for an anonymous visitor. ``owner`` is
    the key a `GameSession` / analysis job records: the player uuid, or `anon:<digest>`, or
    ``None`` for an anonymous caller that holds no anonymous id yet (it owns nothing).
    """

    player_uuid: Optional[str]
    owner: Optional[str]

    @property
    def anonymous(self) -> bool:
        return self.player_uuid is None


def anon_cookie_name() -> str:
    return ANON_COOKIE_ONLINE if config.RUN_MODE == "online" else ANON_COOKIE_LAN


@lru_cache(maxsize=1)
def _mac_key() -> bytes:
    return secrets.token_bytes(32)


def _mac(anon_id: str) -> str:
    return hmac.new(_mac_key(), _MAC_CONTEXT + anon_id.encode(), hashlib.sha256).hexdigest()


def anonymous_owner(anon_id: str) -> str:
    """The session owner an anonymous id maps to; only this digest is ever kept server side."""
    digest = hashlib.sha256(_OWNER_CONTEXT + anon_id.encode()).hexdigest()
    return f"{ANONYMOUS_OWNER_PREFIX}{digest}"


def _read_anon_id(request: Request) -> Optional[str]:
    raw = request.cookies.get(anon_cookie_name(), "")
    if not _COOKIE_SHAPE.match(raw):
        return None
    anon_id, _, mac = raw.partition(".")
    return anon_id if hmac.compare_digest(mac, _mac(anon_id)) else None


def _issue_anon_cookie(response: Response) -> str:
    anon_id = secrets.token_urlsafe(ANON_ID_BYTES)
    response.set_cookie(
        anon_cookie_name(), f"{anon_id}.{_mac(anon_id)}",
        max_age=int(config.GAME_SESSION_TTL_SECONDS),  # no longer useful than the sessions it reaches
        httponly=True, samesite="lax", secure=config.RUN_MODE == "online", path="/",
    )
    return anon_id


def viewer(request: Request, ctx: Optional[AuthContext] = Depends(current_context)) -> Viewer:
    """The caller for reads and per-session routes; never issues a cookie."""
    if ctx is not None:
        return Viewer(ctx.account.player_uuid, ctx.account.player_uuid)
    anon_id = _read_anon_id(request)
    return Viewer(None, anonymous_owner(anon_id) if anon_id else None)


def play_viewer(
    request: Request, response: Response, ctx: Optional[AuthContext] = Depends(current_context)
) -> Viewer:
    """The caller for routes that create a session or job: an anonymous one gets an id if needed."""
    if ctx is not None:
        return Viewer(ctx.account.player_uuid, ctx.account.player_uuid)
    anon_id = _read_anon_id(request) or _issue_anon_cookie(response)
    return Viewer(None, anonymous_owner(anon_id))


def require_login(viewer_: Viewer) -> str:
    """The player uuid of a logged-in viewer; 401 for an anonymous one (writes, private data)."""
    if viewer_.player_uuid is None:
        raise HTTPException(401, {"code": "unauthenticated"})
    return viewer_.player_uuid
