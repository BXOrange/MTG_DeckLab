"""Tests for the backend's catch-all reverse proxy to the frontend.

Reference: mtg_analyzer/api/frontend_proxy.py, mtg_analyzer/config.py
(FRONTEND_ORIGIN) — the backend forwards anything outside /api//ws to the
frontend static server so a browser only needs to reach one port.
"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx2 as httpx
from fastapi.testclient import TestClient

from mtg_analyzer.api.app import app
from mtg_analyzer.api.dependencies import get_frontend_proxy_client

client = TestClient(app)

_FIXTURE_BODY = b"<html>frontend fixture</html>"


class _FixtureHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - stdlib method name
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("X-Fixture", "frontend")
        self.end_headers()
        self.wfile.write(_FIXTURE_BODY)

    def log_message(self, *_args: object) -> None:  # keep test output quiet
        pass


def _start_fixture_server() -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FixtureHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_proxies_unmatched_path_to_frontend():
    server = _start_fixture_server()
    port = server.server_address[1]
    app.dependency_overrides[get_frontend_proxy_client] = lambda: httpx.Client(
        base_url=f"http://127.0.0.1:{port}"
    )
    try:
        response = client.get("/index.html")
        assert response.status_code == 200
        assert response.content == _FIXTURE_BODY
        assert response.headers["x-fixture"] == "frontend"
    finally:
        app.dependency_overrides.pop(get_frontend_proxy_client, None)
        server.shutdown()


def test_api_route_is_not_shadowed_by_the_proxy():
    server = _start_fixture_server()
    port = server.server_address[1]
    app.dependency_overrides[get_frontend_proxy_client] = lambda: httpx.Client(
        base_url=f"http://127.0.0.1:{port}"
    )
    try:
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
    finally:
        app.dependency_overrides.pop(get_frontend_proxy_client, None)
        server.shutdown()


def test_unreachable_frontend_returns_502():
    # Nothing listens here — a closed port on loopback refuses the connection.
    app.dependency_overrides[get_frontend_proxy_client] = lambda: httpx.Client(
        base_url="http://127.0.0.1:1"
    )
    try:
        response = client.get("/some/asset.js")
        assert response.status_code == 502
    finally:
        app.dependency_overrides.pop(get_frontend_proxy_client, None)
