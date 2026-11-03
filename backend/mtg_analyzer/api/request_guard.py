"""Browser-facing request guard: Host allowlist, WebSocket Origin check and
CSRF rejection for unsafe methods (BUG-40/41/42).

The app has no authentication, so the only thing keeping a web page the user
happens to open from driving it is that the browser refuses cross-origin
reads. Three holes bypass that, and this one pure-ASGI middleware (it must
cover `websocket` scopes too, which `BaseHTTPMiddleware` does not) closes
them from a single allowlist:

* DNS rebinding: a page on `attacker.example` re-resolves to 127.0.0.1 and
  becomes "same origin" with the API. The request still carries
  `Host: attacker.example`, so a Host allowlist stops it (400).
* Cross-site WebSocket hijacking: CORS does not apply to WS. Browsers always
  send `Origin` on the handshake; a foreign one is closed with 1008.
* CSRF through simple requests: multipart uploads and body-less POSTs need no
  preflight. An unsafe method from a foreign origin is refused with 403.

Non-browser clients (MCP stdio client, scripts, `TestClient`) send no
`Origin` and no `Sec-Fetch-Site`; they are not a CSRF vector, so a request
with neither header is accepted. Only the Host check applies to them.
"""

from __future__ import annotations

import hmac
import ipaddress
import re
from urllib.parse import urlsplit

from starlette.types import ASGIApp, Receive, Scope, Send

from mtg_analyzer import config
from mtg_analyzer.services import network_gate

#: The frontend is a plain static server with no backend origin baked in, so
#: any local port is allowed rather than hardcoding one.
LOCAL_DEV_ORIGIN_REGEX = r"http://(localhost|127\.0\.0\.1):\d+"
_LOCAL_DEV_ORIGIN = re.compile(LOCAL_DEV_ORIGIN_REGEX)

#: Host names that always reach this server: loopback by name and address.
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

#: `--host` values meaning "every interface". The legitimate Host header then
#: is whatever address the LAN client typed, which we cannot enumerate.
WILDCARD_BIND_HOSTS = frozenset({"0.0.0.0", "::"})

#: Methods that never change state; everything else is "unsafe" (RFC 9110 9.2.1).
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})

#: Fetch-metadata values a browser sends for requests the user's own page made.
#: `none` = user-initiated navigation. `same-site`/`cross-site` are refused.
SAME_ORIGIN_FETCH_SITES = frozenset({"same-origin", "none"})

#: RFC 6455 policy-violation close code, also used by the lobby for bad auth.
WS_POLICY_VIOLATION = 1008


def _split_host(value: str) -> str:
    """Hostname of a `Host` header / URL netloc: port and brackets stripped, lowercased."""
    value = value.strip().lower()
    if value.startswith("["):
        return value[1:].split("]", 1)[0]
    return value.rsplit(":", 1)[0] if value.count(":") == 1 else value


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def allowed_hosts() -> frozenset[str]:
    """Exact host names accepted in `Host`: loopback, the `--host` bind
    address (when concrete) and `config.EXTRA_ALLOWED_HOSTS`."""
    hosts = set(LOOPBACK_HOSTS) | {h.lower() for h in config.EXTRA_ALLOWED_HOSTS}
    bind = config.BIND_HOST.lower()
    if bind and bind not in WILDCARD_BIND_HOSTS:
        hosts.add(bind)
    return frozenset(hosts)


def is_allowed_host(host_header: str) -> bool:
    host = _split_host(host_header)
    if host in allowed_hosts():
        return True
    # LAN opt-in with a wildcard bind: any IP literal is fine. DNS rebinding
    # needs a *name* the attacker controls, and an IP literal cannot be rebound.
    return config.BIND_HOST.lower() in WILDCARD_BIND_HOSTS and _is_ip_literal(host)


def is_allowed_origin(origin: str, host_header: str) -> bool:
    """`Origin` is ours: a local dev origin, the server's own origin (its
    netloc equals the already-validated Host), or an allowed LAN host."""
    if _LOCAL_DEV_ORIGIN.fullmatch(origin):
        return True
    netloc = urlsplit(origin).netloc.lower()
    if not netloc:  # "null" (sandboxed iframe, file://) and garbage
        return False
    # Never the wildcard IP-literal rule: that is sound for Host (rebinding)
    # but would admit a page served from any attacker IP as an Origin.
    return netloc == host_header.strip().lower() or _split_host(netloc) in allowed_hosts()


def _headers(scope: Scope) -> dict[str, str]:
    return {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}


def _csrf_blocked(method: str, headers: dict[str, str]) -> bool:
    if method.upper() in SAFE_METHODS:
        return False
    origin = headers.get("origin")
    if origin is not None:
        return not is_allowed_origin(origin, headers.get("host", ""))
    # No Origin: a non-browser client, or a browser that omitted it. Browsers
    # that send fetch metadata tell us whether the page was ours.
    site = headers.get("sec-fetch-site")
    return site is not None and site not in SAME_ORIGIN_FETCH_SITES


def _session_csrf_blocked(scope: Scope, headers: dict[str, str]) -> bool:
    """PLR-9a, plan §3: a request carrying a *valid* session cookie must present the
    session-bound CSRF token on unsafe methods, even when it sends neither `Origin` nor
    `Sec-Fetch-Site` (the exemption above is only for cookie-less clients such as MCP,
    scripts and `TestClient`). An unknown/expired cookie authenticates nothing, so it passes."""
    from http.cookies import SimpleCookie, CookieError

    raw = headers.get("cookie")
    if not raw:
        return False
    # Imported here: api.auth imports api.dependencies, which must not load while this module imports.
    from mtg_analyzer.api.auth import CSRF_HEADER, session_cookie_name
    from mtg_analyzer.api.dependencies import get_account_store

    try:
        jar = SimpleCookie(raw)
    except CookieError:
        return False
    morsel = jar.get(session_cookie_name())
    if morsel is None:
        return False
    # Honour dependency overrides so tests (and any embedding app) can swap the store.
    overrides = getattr(scope.get("app"), "dependency_overrides", None) or {}
    resolved = overrides.get(get_account_store, get_account_store)().resolve_session(morsel.value)
    if resolved is None:
        return False
    sent = headers.get(CSRF_HEADER, "")
    return not sent or not hmac.compare_digest(sent.encode(), resolved[1].csrf_token.encode())


class RequestGuardMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        kind = scope["type"]
        if kind not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        headers = _headers(scope)
        reason = None
        client = scope.get("client")
        if not network_gate.peer_allowed(client[0] if client else None, network_gate.active_allowlist()):
            reason = ("network", 403)  # PLR-9a peer allowlist; the Host check below stays as well
        elif not is_allowed_host(headers.get("host", "")):
            reason = ("host", 400)
        elif kind == "websocket":
            origin = headers.get("origin")  # absent = non-browser client
            if origin is not None and not is_allowed_origin(origin, headers.get("host", "")):
                reason = ("origin", 403)
        elif _csrf_blocked(scope["method"], headers):
            reason = ("cross-origin request", 403)
        elif scope["method"].upper() not in SAFE_METHODS and _session_csrf_blocked(scope, headers):
            reason = ("missing or wrong CSRF token", 403)
        if reason is None:
            await self.app(scope, receive, send)
            return
        what, status = reason
        if kind == "websocket":
            await receive()  # consume websocket.connect before refusing it
            await send({"type": "websocket.close", "code": WS_POLICY_VIOLATION})
            return
        body = f"Rejected: {what} not allowed".encode()
        await send({
            "type": "http.response.start", "status": status,
            "headers": [(b"content-type", b"text/plain"), (b"content-length", str(len(body)).encode())],
        })
        await send({"type": "http.response.body", "body": body})
