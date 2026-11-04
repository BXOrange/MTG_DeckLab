"""Dedicated loopback-only admin listener (PLR-19).

Behind `--behind-tls-proxy` the main port cannot prove that a request is local (BUG-52): a
same-host proxy sends exactly the shape of a local request. So the operator on the server machine
gets a second socket, `127.0.0.1:<--admin-port>`, served by **this same process** (same app, same
in-memory state: disabling a player here still closes that player's sockets). A request that
arrives on it is local by construction; it needs name + password but no second factor.

How it runs: the main uvicorn process starts a second `uvicorn.Server` as a task in its own event
loop from the app lifespan (`start`/`stop`, called by `api/app.py`). The lifespan therefore runs
once; the listener's server has lifespan off, no signal handlers of its own, and a pre-bound
loopback socket, so a port clash fails the start loudly instead of silently running without it.

Recognition is by the socket, not by headers: this wrapper is the app of the only server that owns
that socket, checks the ASGI `server` address, and sets `network_gate.ADMIN_LISTENER_SCOPE_KEY` in
the scope (never client-suppliable). It refuses any forwarding header, serves only the admin page
and `/api/admin`, and answers 404 for everything else.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import socket
from typing import Optional

import uvicorn
from starlette.types import ASGIApp, Receive, Scope, Send

from mtg_analyzer import config
from mtg_analyzer.services import network_gate

logger = logging.getLogger(__name__)

#: Path prefixes the listener serves: the admin page (and its assets) and the admin API.
ADMIN_PATH_PREFIXES = ("/admin", "/api/admin")

#: Exact extra paths: the admin page's MCP token button posts here (admin-only route, `mcp_settings.py`).
ADMIN_EXACT_PATHS = frozenset({"/api/mcp-settings/rotate"})

#: How long `start` waits for the listener to come up before giving up (seconds).
START_TIMEOUT_SECONDS = 10.0
START_POLL_SECONDS = 0.02

#: How long `stop` waits for in-flight admin requests before abandoning the task (seconds).
STOP_TIMEOUT_SECONDS = 10.0

#: Listen backlog of the admin socket: one operator, a handful of tabs.
LISTEN_BACKLOG = 16

_REFUSED_FORWARDED = b"Rejected: forwarded requests are not served on the admin listener"
_NOT_FOUND = b"Not found"


def is_admin_path(path: str) -> bool:
    """Whether `path` belongs to the admin surface (no dot segments, so a prefix cannot be escaped)."""
    if ".." in path.split("/") or "//" in path or "\\" in path:
        return False
    if path in ADMIN_EXACT_PATHS:
        return True
    return any(path == prefix or path.startswith(prefix + "/") for prefix in ADMIN_PATH_PREFIXES)


def _has_forwarding_header(scope: Scope) -> bool:
    for raw_name, _ in scope.get("headers", ()):
        name = raw_name.decode("latin-1").lower()
        if name in network_gate.FORWARDING_HEADERS or name.startswith("x-forwarded-"):
            return True
    return False


class AdminListenerApp:
    """ASGI wrapper around the real app, attached only to the admin listener's server."""

    def __init__(self, app: ASGIApp, port: int, host: str = config.ADMIN_LISTENER_HOST) -> None:
        self.app = app
        self.port = port
        self.host = host

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        kind = scope["type"]
        if kind == "websocket":
            await receive()
            await send({"type": "websocket.close", "code": 1008})
            return
        if kind != "http":
            return
        server = scope.get("server")
        if not server or server[1] != self.port or not network_gate.is_loopback(server[0]):
            await self._reply(send, 404, _NOT_FOUND)  # not arriving on our own socket: never local
            return
        if _has_forwarding_header(scope):
            await self._reply(send, 403, _REFUSED_FORWARDED)
            return
        if not is_admin_path(scope["path"]):
            await self._reply(send, 404, _NOT_FOUND)
            return
        await self.app({**scope, network_gate.ADMIN_LISTENER_SCOPE_KEY: True}, receive, send)

    @staticmethod
    async def _reply(send: Send, status: int, body: bytes) -> None:
        await send({
            "type": "http.response.start", "status": status,
            "headers": [(b"content-type", b"text/plain"), (b"content-length", str(len(body)).encode()),
                        (b"cache-control", b"no-store")],
        })
        await send({"type": "http.response.body", "body": body})


class _EmbeddedServer(uvicorn.Server):
    """A uvicorn server living inside another server's event loop: it must not touch process signals."""

    @contextlib.contextmanager
    def capture_signals(self):  # uvicorn >= 0.29
        yield

    def install_signal_handlers(self) -> None:  # older uvicorn
        return None


class AdminListener:
    def __init__(self, app: ASGIApp, port: int, log_level: str = "warning") -> None:
        self.port = port
        self._sock: Optional[socket.socket] = None
        self._server = _EmbeddedServer(uvicorn.Config(
            AdminListenerApp(app, port), lifespan="off", access_log=False, log_level=log_level,
            ws="none",
        ))
        self._task: Optional[asyncio.Task] = None

    def _bind(self) -> socket.socket:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((config.ADMIN_LISTENER_HOST, self.port))
            sock.listen(LISTEN_BACKLOG)
            sock.setblocking(False)
        except OSError as exc:
            sock.close()
            raise RuntimeError(
                f"admin listener cannot bind {config.ADMIN_LISTENER_HOST}:{self.port}: {exc}"
            ) from exc
        return sock

    async def start(self) -> None:
        self._sock = self._bind()
        self._task = asyncio.create_task(self._server.serve(sockets=[self._sock]))
        waited = 0.0
        while not self._server.started:
            if self._task.done():
                self._task.result()  # re-raises the failure
                raise RuntimeError("admin listener stopped during start")
            if waited >= START_TIMEOUT_SECONDS:
                await self.stop()
                raise RuntimeError("admin listener did not start in time")
            await asyncio.sleep(START_POLL_SECONDS)
            waited += START_POLL_SECONDS
        logger.warning("admin listener on http://%s:%d (local only: /admin and /api/admin)",
                       config.ADMIN_LISTENER_HOST, self.port)

    async def stop(self) -> None:
        self._server.should_exit = True
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, STOP_TIMEOUT_SECONDS)
            except (asyncio.TimeoutError, asyncio.CancelledError, Exception):  # noqa: BLE001 - shutting down
                self._task.cancel()
            self._task = None
        if self._sock is not None:
            self._sock.close()
            self._sock = None
