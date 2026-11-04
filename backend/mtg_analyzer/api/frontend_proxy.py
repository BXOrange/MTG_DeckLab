"""Catch-all: reverse-proxy anything outside /api and /ws to the frontend.

Lets a browser reach the whole app through the backend's single port
instead of two origins (frontend static server + backend API), which is
what made CORS necessary in the first place. This is a plain
server-to-server HTTP call to `config.FRONTEND_ORIGIN` (by default
`setup/start.py`'s `no_cache_server.py`) — invisible to, and not subject
to, browser CORS.

Must be registered LAST in `api/app.py` (after every other router and the
inline `/api/health` route): FastAPI/Starlette matches routes in
registration order, and `/{path:path}` would otherwise swallow everything.
The `_is_reserved_path` guard below is a second, defensive line against the
same mistake — a route added below this router in the future would 404
here instead of being silently proxied to the frontend.
"""

from __future__ import annotations

import httpx2 as httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from mtg_analyzer.api.dependencies import get_frontend_proxy_client
from mtg_analyzer.services import network_gate

router = APIRouter(tags=["frontend-proxy"])

#: Headers that must not be copied verbatim from the upstream (frontend)
#: response: they describe *that* connection (chunking, keep-alive) or are
#: recomputed by Starlette/uvicorn for *this* response (content-length,
#: date, server) — passing the upstream's own would otherwise duplicate
#: them alongside uvicorn's, since both this response and the upstream one
#: legitimately have a Date/Server header of their own.
_HOP_BY_HOP_HEADERS = {"connection", "content-length", "transfer-encoding", "date", "server"}

#: The static server's own CSP allows loopback connects for `--frontend-only`;
#: behind this proxy the backend's `SecurityHeadersMiddleware` sets the policy.
_HOP_BY_HOP_HEADERS |= {"content-security-policy"}


#: The static administration page lives under this prefix of the frontend tree (PLR-9d).
ADMIN_PAGE_PREFIX = "admin"

#: Policy of the admin page (plan section 6): its own, strict CSP - no inline script, no external
#: source, no form posts - because the password is typed on the same origin as player content.
ADMIN_PAGE_CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'none'; object-src 'none'"
)


def _is_admin_path(path: str) -> bool:
    return path == ADMIN_PAGE_PREFIX or path.startswith(ADMIN_PAGE_PREFIX + "/")


def _is_reserved_path(path: str) -> bool:
    return path == "api" or path.startswith("api/") or path == "ws" or path.startswith("ws/")


@router.get("/{path:path}")
def proxy_to_frontend(
    path: str,
    request: Request,
    client: httpx.Client = Depends(get_frontend_proxy_client),
) -> Response:
    if _is_reserved_path(path):
        return Response(status_code=404)

    admin_page = _is_admin_path(path)
    if admin_page:
        # Loopback only in every run mode, also when a LAN client reaches the page through this
        # proxy (plan sections 3 and 6): the proxy answers 403 before it asks the frontend server.
        peer = request.client.host if request.client else None
        if not network_gate.is_local_request(peer, {k.lower(): v for k, v in request.headers.items()}):
            return Response(status_code=403, content="Rejected: admin page is local only", media_type="text/plain")
        if path.rstrip("/") == ADMIN_PAGE_PREFIX:
            path = f"{ADMIN_PAGE_PREFIX}/index.html"

    try:
        upstream = client.get(f"/{path}", params=request.query_params)
    except httpx.HTTPError as exc:
        return Response(
            content=f"Frontend server unreachable at {client.base_url}: {exc}",
            status_code=502,
            media_type="text/plain",
        )

    headers = {k: v for k, v in upstream.headers.items() if k.lower() not in _HOP_BY_HOP_HEADERS}
    if admin_page:
        headers = {k: v for k, v in headers.items() if k.lower() != "cache-control"}
        headers["Content-Security-Policy"] = ADMIN_PAGE_CSP
        headers["Cache-Control"] = "no-store"
    return Response(content=upstream.content, status_code=upstream.status_code, headers=headers)
