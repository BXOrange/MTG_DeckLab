"""PLR-19: the dedicated loopback-only admin listener (``api/admin_listener.py``) for ``--behind-tls-proxy``.

The wrapper is exercised through ``TestClient`` (its ``base_url`` port becomes the ASGI ``server``
address) and the real two-server arrangement through a live socket on a free port. Throwaway stores only.
"""

import asyncio
import socket
import urllib.error
import urllib.request

import pytest
from fastapi.testclient import TestClient

from mtg_analyzer import config
from mtg_analyzer.api.admin_listener import AdminListener, AdminListenerApp, is_admin_path
from mtg_analyzer.api.app import app
from mtg_analyzer.services import network_gate as ng
from tests.api.test_api_admin_mfa import (  # noqa: F401 - fixtures are imported by name
    LOCAL, basic, code_for, enrol, env, make_admin,
)

pytestmark = pytest.mark.real_auth

ADMIN_PORT = 18766
ON_ADMIN_PORT = dict(base_url=f"http://127.0.0.1:{ADMIN_PORT}", client=("127.0.0.1", 50000))


@pytest.fixture
def proxy(monkeypatch):
    monkeypatch.setattr(config, "BEHIND_TLS_PROXY", True)
    monkeypatch.setattr(config, "RUN_MODE", "online")
    monkeypatch.setattr(config, "TRUSTED_PROXIES", "127.0.0.0/8,::1/128")


@pytest.fixture
def admin_client(proxy):
    return TestClient(AdminListenerApp(app, ADMIN_PORT), **ON_ADMIN_PORT)


def test_admin_port_request_is_local_in_proxy_mode_without_a_code(env, proxy, admin_client):
    make_admin(env)
    secret, _, _ = enrol(TestClient(AdminListenerApp(app, ADMIN_PORT), **ON_ADMIN_PORT), env)
    assert admin_client.get("/api/admin/players", headers=basic()).status_code == 200  # enrolled, no code
    assert admin_client.get("/api/admin/state").json()["second_factor_required"] is False


def test_unenrolled_online_admin_works_on_the_admin_port(env, proxy, admin_client):
    make_admin(env)
    assert admin_client.get("/api/admin/whoami", headers=basic()).status_code == 200


def test_the_proxied_port_is_still_never_local(env, proxy):
    make_admin(env)
    proxied = TestClient(app, **LOCAL)  # loopback peer, loopback Host: the nginx default shape (BUG-52)
    assert proxied.get("/api/admin/players", headers=basic()).status_code == 403
    assert not ng.is_local_request("127.0.0.1", {"host": "127.0.0.1"})
    # a spoofed scope marker is not a header, so a client cannot supply it
    assert proxied.get("/api/admin/players", headers=basic(**{ng.ADMIN_LISTENER_SCOPE_KEY: "1"})).status_code == 403


@pytest.mark.parametrize("header", ["X-Forwarded-For", "Forwarded", "X-Real-IP", "X-Forwarded-Proto", "X-Forwarded-Host"])
def test_forwarding_headers_on_the_admin_port_are_refused(env, proxy, admin_client, header):
    make_admin(env)
    assert admin_client.get("/api/admin/players", headers=basic(**{header: "203.0.113.9"})).status_code == 403
    assert admin_client.get("/admin", headers={header: "203.0.113.9"}).status_code == 403


@pytest.mark.parametrize("path", [
    "/", "/index.html", "/api/health", "/api/decks", "/api/auth/login", "/api/game/sessions", "/ws/lobby",
    "/administrator", "/api/administrator", "/js/app.js",
])
def test_only_the_admin_surface_is_served_on_the_admin_port(proxy, admin_client, path):
    assert admin_client.get(path).status_code == 404


def test_admin_paths_are_recognised_without_escaping_the_prefix():
    for ok in ("/admin", "/admin/", "/admin/admin.js", "/api/admin/state", "/api/mcp-settings/rotate"):
        assert is_admin_path(ok)
    for bad in ("/admin/../index.html", "/api/admin/../decks", "//admin", "/admin/..\\x", "/api/mcp-settings", "/"):
        assert not is_admin_path(bad)


def test_a_request_not_on_the_admin_socket_is_never_local(env, proxy):
    make_admin(env)
    wrong_port = TestClient(AdminListenerApp(app, ADMIN_PORT), base_url="http://127.0.0.1:9999", client=("127.0.0.1", 1))
    assert wrong_port.get("/api/admin/players", headers=basic()).status_code == 404


def test_the_admin_listener_never_serves_a_non_loopback_peer(env, proxy):
    make_admin(env)
    remote = TestClient(AdminListenerApp(app, ADMIN_PORT), base_url=ON_ADMIN_PORT["base_url"], client=("203.0.113.9", 1))
    assert remote.get("/api/admin/players", headers=basic()).status_code == 403


def test_wrong_password_on_the_admin_port_is_refused(env, proxy, admin_client):
    make_admin(env)
    assert admin_client.get("/api/admin/players", headers=basic(password="not-the-password-123")).status_code == 401


# -- a real second socket in the same event loop ---------------------------------------------------

def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _echo_app(scope, receive, send):
    body = str(bool(scope.get(ng.ADMIN_LISTENER_SCOPE_KEY))).encode()
    await send({"type": "http.response.start", "status": 200, "headers": [(b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})


def _fetch(url: str, headers=None):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}), timeout=5) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, ""


def test_the_listener_serves_on_a_real_loopback_socket_and_stops_cleanly():
    port = _free_port()

    async def scenario():
        listener = AdminListener(_echo_app, port)
        await listener.start()
        try:
            ok = await asyncio.to_thread(_fetch, f"http://127.0.0.1:{port}/api/admin/x")
            other = await asyncio.to_thread(_fetch, f"http://127.0.0.1:{port}/api/decks")
            forged = await asyncio.to_thread(_fetch, f"http://127.0.0.1:{port}/api/admin/x", {"X-Forwarded-For": "1.2.3.4"})
        finally:
            await listener.stop()
        return ok, other, forged

    ok, other, forged = asyncio.run(scenario())
    assert ok == (200, "True")  # the scope marker is set by the listener only
    assert other[0] == 404 and forged[0] == 403
    with pytest.raises(OSError), socket.create_connection(("127.0.0.1", port), timeout=1):
        pass  # the socket is closed after stop


def test_the_listener_binds_loopback_only():
    port = _free_port()

    async def scenario():
        listener = AdminListener(_echo_app, port)
        await listener.start()
        try:
            return listener._sock.getsockname()
        finally:
            await listener.stop()

    assert asyncio.run(scenario())[0] == config.ADMIN_LISTENER_HOST == "127.0.0.1"


def test_a_taken_port_fails_the_start_loudly():
    with socket.socket() as blocker:
        blocker.bind(("127.0.0.1", 0))
        blocker.listen()
        taken = blocker.getsockname()[1]

        async def scenario():
            await AdminListener(_echo_app, taken).start()

        with pytest.raises(RuntimeError, match="cannot bind"):
            asyncio.run(scenario())
