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

import ipaddress
import re
from urllib.parse import urlsplit

from starlette.types import ASGIApp, Receive, Scope, Send

from mtg_analyzer import config

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
        if not is_allowed_host(headers.get("host", "")):
            reason = ("host", 400)
        elif kind == "websocket":
            origin = headers.get("origin")  # absent = non-browser client
            if origin is not None and not is_allowed_origin(origin, headers.get("host", "")):
                reason = ("origin", 403)
        elif _csrf_blocked(scope["method"], headers):
            reason = ("cross-origin request", 403)
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
