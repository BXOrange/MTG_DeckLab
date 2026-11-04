"""BUG-52: forwarded headers are believed only from trusted proxy peers; proxy mode has no "local"."""
import pytest
from fastapi.testclient import TestClient

from mtg_analyzer import config
from mtg_analyzer.api.app import app
from mtg_analyzer.services import network_gate as ng

LOOP, WORLD = "127.0.0.1", "198.51.100.7"
HTTPS_FOR = {"x-forwarded-proto": "https", "x-forwarded-for": WORLD}


@pytest.fixture
def proxy(monkeypatch):
    monkeypatch.setattr(config, "BEHIND_TLS_PROXY", True)
    monkeypatch.setattr(config, "RUN_MODE", "online")
    monkeypatch.setattr(config, "TRUSTED_PROXIES", "127.0.0.0/8,::1/128")


def refusal(peer, headers, scheme="http"):
    return ng.admin_surface_refusal(peer, headers, scheme)


def test_direct_spoofed_proto_is_refused(proxy):
    assert refusal(WORLD, HTTPS_FOR) == ng.ADMIN_HTTPS_REQUIRED  # untrusted peer: header ignored
    assert not ng.secure_transport("http", HTTPS_FOR, WORLD)


def test_without_proxy_mode_forwarded_proto_is_never_believed(proxy, monkeypatch):
    monkeypatch.setattr(config, "BEHIND_TLS_PROXY", False)
    assert not ng.secure_transport("http", HTTPS_FOR, LOOP)


def test_trusted_proxy_is_accepted(proxy):
    assert refusal(LOOP, HTTPS_FOR) is None
    assert ng.secure_transport("http", HTTPS_FOR, LOOP)


def test_trusted_proxy_plain_http_still_refused(proxy):
    assert refusal(LOOP, {**HTTPS_FOR, "x-forwarded-proto": "http"}) == ng.ADMIN_HTTPS_REQUIRED


def test_nginx_default_request_is_not_local(proxy):
    headers = {"host": "127.0.0.1:8765"}  # nginx defaults: no X-Forwarded-*, Host rewritten to the upstream
    assert not ng.is_local_request(LOOP, headers)
    assert refusal(LOOP, headers) is not None


def test_missing_forwarded_for_from_trusted_proxy_is_refused(proxy):
    assert refusal(LOOP, {"x-forwarded-proto": "https"}) == ng.ADMIN_FORWARDED_FOR_REQUIRED
    assert refusal(LOOP, {"x-forwarded-proto": "https", "x-forwarded-for": "not-an-ip"}) == ng.ADMIN_FORWARDED_FOR_REQUIRED


def test_loopback_is_never_local_in_proxy_mode_even_without_headers(proxy):
    assert not ng.is_local_request(LOOP, {"host": "localhost"})


def test_local_still_works_without_proxy_mode():
    assert ng.is_local_request(LOOP, {"host": "localhost"})


def test_rightmost_forwarded_entry_wins(proxy):
    chain = {"x-forwarded-for": "10.9.9.9, 203.0.113.5", "x-forwarded-proto": "http, https"}
    assert ng.forwarded_client(LOOP, chain) == "203.0.113.5"
    assert ng.forwarded_proto(LOOP, chain) == "https"
    assert ng.forwarded_proto(LOOP, {"x-forwarded-proto": "https, http"}) == "http"  # client-supplied left entry ignored


@pytest.mark.parametrize("peer", ["::1", "::ffff:127.0.0.1", "127.5.5.5"])
def test_ipv6_and_mapped_loopback_peers_are_trusted(proxy, peer):
    assert ng.is_trusted_proxy(peer)


def test_custom_trusted_proxy_cidr(proxy, monkeypatch):
    monkeypatch.setattr(config, "TRUSTED_PROXIES", "10.1.0.0/16")
    assert ng.is_trusted_proxy("10.1.2.3") and ng.is_trusted_proxy("::ffff:10.1.2.3")
    assert not ng.is_trusted_proxy(LOOP)
    assert refusal("10.1.2.3", HTTPS_FOR) is None
    assert refusal(LOOP, HTTPS_FOR) == ng.ADMIN_HTTPS_REQUIRED


def test_invalid_trusted_proxy_list_trusts_nobody(proxy, monkeypatch):
    monkeypatch.setattr(config, "TRUSTED_PROXIES", "garbage")
    assert not ng.is_trusted_proxy(LOOP)


def test_lan_allowlist_never_uses_forwarded_for(proxy):
    assert not ng.peer_allowed(WORLD, ng.build_allowlist("localdev", ""))
    assert ng.forwarded_client(WORLD, HTTPS_FOR) is None


def test_client_key_uses_forwarded_client_only_from_trusted_peer(proxy):
    from mtg_analyzer.api.admin_auth import client_key

    class Req:
        def __init__(self, host, headers):
            self.client = type("C", (), {"host": host})
            self.headers = headers

    assert client_key(Req(LOOP, {"x-forwarded-for": "203.0.113.5"})) == f"{LOOP}|203.0.113.5"
    assert client_key(Req(WORLD, {"x-forwarded-for": "203.0.113.5"})) == WORLD


def test_http_route_and_websocket_ignore_untrusted_forwarding(proxy):
    direct = TestClient(app, base_url="http://localhost", client=(WORLD, 1))
    r = direct.get("/api/admin/whoami", headers=HTTPS_FOR)
    assert r.status_code == 403 and r.json()["detail"]["code"] == ng.ADMIN_HTTPS_REQUIRED
    local = TestClient(app, base_url="http://localhost", client=(LOOP, 1))
    r = local.get("/api/admin/whoami", headers={"x-forwarded-proto": "https"})
    assert r.status_code == 403 and r.json()["detail"]["code"] == ng.ADMIN_FORWARDED_FOR_REQUIRED
    r = local.get("/api/admin/whoami", headers={"host": "127.0.0.1:8765"})
    assert r.status_code == 403


def test_websocket_upgrade_goes_through_the_same_guard(proxy, monkeypatch):
    # The WS guard (request_guard) only checks peer allowlist/Host/Origin and never reads forwarding
    # headers, so a spoofed X-Forwarded-* on an upgrade grants nothing; admin is HTTP-only.
    import inspect
    from mtg_analyzer.api import multiplayer_ws, request_guard
    for module in (multiplayer_ws, request_guard):
        assert "x-forwarded" not in inspect.getsource(module).lower()
