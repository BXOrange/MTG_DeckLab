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

router = APIRouter(tags=["frontend-proxy"])

#: Headers that must not be copied verbatim from the upstream (frontend)
#: response: they describe *that* connection (chunking, keep-alive) or are
#: recomputed by Starlette/uvicorn for *this* response (content-length,
#: date, server) — passing the upstream's own would otherwise duplicate
#: them alongside uvicorn's, since both this response and the upstream one
#: legitimately have a Date/Server header of their own.
_HOP_BY_HOP_HEADERS = {"connection", "content-length", "transfer-encoding", "date", "server"}


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

    try:
        upstream = client.get(f"/{path}", params=request.query_params)
    except httpx.HTTPError as exc:
        return Response(
            content=f"Frontend server unreachable at {client.base_url}: {exc}",
            status_code=502,
            media_type="text/plain",
        )

    headers = {k: v for k, v in upstream.headers.items() if k.lower() not in _HOP_BY_HOP_HEADERS}
    return Response(content=upstream.content, status_code=upstream.status_code, headers=headers)
