"""Security response headers for every HTTP response (BUG-44).

Top-level module (not under `api/`, whose package init imports the app) and
dependency-free on purpose: `setup/no_cache_server.py` (the frontend-only
static server) imports `csp_for` / `STATIC_SECURITY_HEADERS` so both servers
send the same policy. `SecurityHeadersMiddleware` is pure ASGI, like
`RequestGuardMiddleware`, so it also covers the frontend reverse-proxy
responses and error responses raised by other middleware.

Headers already set by a route are never overridden, so a route can send a
stricter policy (the uploaded-image routes use `ASSET_CSP`).
"""

from __future__ import annotations

import re

#: Hostname[:port] shapes allowed into a CSP source. The Host header has been
#: vetted by `RequestGuardMiddleware`, but a CSP is a header value, so never
#: interpolate anything that could carry `;`, spaces or CR/LF.
_SAFE_HOST = re.compile(r"[A-Za-z0-9.\-]+|\[[0-9A-Fa-f:]+\]")
_SAFE_AUTHORITY = re.compile(rf"(?:{_SAFE_HOST.pattern})(?::\d{{1,5}})?")

#: Loopback origins the `--frontend-only` page (served on its own port) talks to.
#: CSP host-source wildcard port `:*` is the only way to say "any local port".
FRONTEND_DEV_HTTP_SOURCES = "http://localhost:* http://127.0.0.1:*"
FRONTEND_DEV_CONNECT_SOURCES = f"{FRONTEND_DEV_HTTP_SOURCES} ws://localhost:* ws://127.0.0.1:*"

#: The one third-party origin the page loads from (token art, see `csp_for`).
SCRYFALL_IMAGE_CDN = "https://cards.scryfall.io"

#: Policy for uploaded images served back: nothing may load or execute, even if
#: a mis-typed file were rendered as a document (`sandbox` also drops script).
ASSET_CSP = "default-src 'none'; style-src 'unsafe-inline'; sandbox"

#: Headers that do not depend on the request.
#: - nosniff: browsers must trust the declared Content-Type (no MIME sniffing).
#: - Referrer-Policy same-origin: no URL (deck/player names ride in paths)
#:   leaks to Scryfall/TCGplayer links, while same-origin tooling keeps working.
#: - X-Frame-Options DENY: legacy twin of `frame-ancestors 'none'`; nothing frames the app.
STATIC_SECURITY_HEADERS: tuple[tuple[str, str], ...] = (
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "same-origin"),
    ("X-Frame-Options", "DENY"),
)


def csp_for(authority: str | None, *, frontend_dev: bool = False) -> str:
    """Content-Security-Policy for the buildless frontend.

    * `script-src 'self'`: there is no inline script, handler or eval in the
      frontend; a script-injection bug can therefore not run (no
      `'unsafe-inline'`/`'unsafe-eval'`).
    * `style-src ... 'unsafe-inline'`: views build `style="..."` attributes and
      set `element.style`; unavoidable without a rewrite.
    * `img-src 'self' data: blob: https://cards.scryfall.io`: card art goes
      through the backend image cache (same origin), but token art URLs
      (`fetchDeckTokens`) are Scryfall CDN URLs the browser loads directly;
      `data:`/`blob:` cover generated art. Referrer-Policy sends it no referrer.
    * `connect-src`: fetch + the lobby WebSocket. `'self'` covers ws on the same
      host in current browsers; older Safari needs the explicit ws/wss source.
    * `frame-ancestors 'none'`, `object-src 'none'`, `base-uri`, `form-action`:
      no clickjacking, plugins, base-tag or form-post hijack.
    """
    connect = ["'self'"]
    images = ["'self'", "data:", "blob:", SCRYFALL_IMAGE_CDN]
    if frontend_dev:
        images.append(FRONTEND_DEV_HTTP_SOURCES)  # card/sleeve images come from the API origin
        connect.append(FRONTEND_DEV_CONNECT_SOURCES)
    if authority and _SAFE_AUTHORITY.fullmatch(authority):
        connect.append(f"ws://{authority} wss://{authority}")
    return "; ".join([
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self' 'unsafe-inline'",
        f"img-src {' '.join(images)}",
        "media-src 'self' blob:",
        f"connect-src {' '.join(connect)}",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ])


class SecurityHeadersMiddleware:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        authority = next(
            (v.decode("latin-1") for k, v in scope["headers"] if k == b"host"), None
        )

        async def send_with_headers(message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {k.lower() for k, _ in headers}
                wanted = list(STATIC_SECURITY_HEADERS) + [
                    ("Content-Security-Policy", csp_for(authority))
                ]
                for name, value in wanted:
                    if name.lower().encode() not in present:
                        headers.append((name.lower().encode(), value.encode()))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)
