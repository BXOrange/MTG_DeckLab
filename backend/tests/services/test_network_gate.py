"""PLR-9a: peer-address allowlist for the run modes."""

import ipaddress

import pytest
from fastapi.testclient import TestClient

from mtg_analyzer import config
from mtg_analyzer.api.app import app
from mtg_analyzer.services import network_gate as ng


def _nets(*cidrs):
    return [ipaddress.ip_network(c) for c in cidrs]


def test_configured_networks_are_the_complete_list_plus_loopback():
    allow = ng.build_allowlist("lan", "192.168.179.0/24", interfaces=lambda: _nets("10.0.0.0/8"))
    assert ng.peer_allowed("192.168.179.20", allow)
    assert ng.peer_allowed("127.0.0.1", allow) and ng.peer_allowed("::1", allow)
    assert not ng.peer_allowed("10.1.2.3", allow)  # interfaces ignored once configured
    assert not ng.peer_allowed("192.168.180.1", allow)


def test_unset_uses_interface_subnets():
    allow = ng.build_allowlist("lan", "", interfaces=lambda: _nets("192.168.1.0/24"))
    assert ng.peer_allowed("192.168.1.77", allow)
    assert not ng.peer_allowed("8.8.8.8", allow)


def test_enumeration_failure_is_loopback_only():
    allow = ng.build_allowlist("lan", "", interfaces=lambda: [])
    assert ng.peer_allowed("127.0.0.1", allow)
    assert not ng.peer_allowed("192.168.1.77", allow) and not ng.peer_allowed("10.0.0.1", allow)


def test_invalid_cidr_is_a_startup_error():
    with pytest.raises(ng.InvalidNetworkError):
        ng.build_allowlist("lan", "192.168.1.0/99", interfaces=lambda: [])


def test_ipv4_mapped_ipv6_and_zone_ids():
    allow = ng.build_allowlist("lan", "192.168.179.0/24")
    assert ng.peer_allowed("::ffff:192.168.179.5", allow)
    assert not ng.peer_allowed("::ffff:192.168.180.5", allow)
    assert ng.peer_allowed("::1%lo0", allow)
    assert not ng.peer_allowed("fe80::1%en0", allow)
    assert not ng.peer_allowed(None, allow) and not ng.peer_allowed("not-an-ip", allow)


def test_modes():
    assert ng.build_allowlist("online", "") is None
    local = ng.build_allowlist("localdev", "192.168.1.0/24")
    assert not ng.peer_allowed("192.168.1.5", local) and ng.peer_allowed("127.0.0.1", local)


@pytest.mark.parametrize("peer,headers,expected", [
    ("127.0.0.1", {"host": "localhost:8765"}, True),
    ("::1", {"host": "[::1]:8765"}, True),
    ("127.0.0.1", {"host": "127.0.0.1"}, True),
    ("192.168.1.5", {"host": "localhost"}, False),
    ("127.0.0.1", {"host": "localhost", "x-forwarded-for": "192.168.1.5"}, False),
    ("127.0.0.1", {"host": "localhost", "forwarded": "for=1.2.3.4"}, False),
    ("127.0.0.1", {"host": "192.168.1.9:8000"}, False),
])
def test_is_local_request(peer, headers, expected):
    assert ng.is_local_request(peer, headers) is expected


@pytest.fixture
def gated(monkeypatch):
    def setup(mode, networks=""):
        monkeypatch.setattr(config, "RUN_MODE", mode)
        monkeypatch.setattr(config, "ALLOWED_NETWORKS", networks)
        monkeypatch.setattr(config, "RUN_MODE_EXPLICIT", True)
        ng.reset_for_tests()
    yield setup
    ng.reset_for_tests()


def test_http_gate_rejects_foreign_peer_and_ignores_forwarded_headers(gated):
    gated("lan", "192.168.179.0/24")
    ok = TestClient(app, client=("192.168.179.8", 5000))
    bad = TestClient(app, client=("192.168.50.8", 5000))
    assert ok.get("/api/health", headers={"Host": "localhost"}).status_code == 200
    assert bad.get("/api/health", headers={"Host": "localhost"}).status_code == 403
    spoof = bad.get("/api/health", headers={"Host": "localhost", "X-Forwarded-For": "192.168.179.8"})
    assert spoof.status_code == 403


def test_ws_gate_closes_foreign_peer(gated):
    from starlette.websockets import WebSocketDisconnect
    gated("lan", "192.168.179.0/24")
    bad = TestClient(app, client=("192.168.50.8", 5000))
    with pytest.raises(WebSocketDisconnect) as exc:
        with bad.websocket_connect("/ws/lobby?name=Ann"):
            pass
    assert exc.value.code == 1008


def test_localdev_rejects_lan_peer_and_online_accepts_any(gated):
    gated("localdev")
    assert TestClient(app, client=("192.168.1.5", 1)).get("/api/health", headers={"Host": "localhost"}).status_code == 403
    gated("online")
    assert TestClient(app, client=("8.8.8.8", 1)).get("/api/health", headers={"Host": "localhost"}).status_code == 200


def test_ungated_without_explicit_mode(monkeypatch):
    monkeypatch.setattr(config, "RUN_MODE_EXPLICIT", False)
    ng.reset_for_tests()
    assert TestClient(app, client=("8.8.8.8", 1)).get("/api/health", headers={"Host": "localhost"}).status_code == 200
