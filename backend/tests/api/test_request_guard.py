"""Host allowlist, WebSocket Origin check and CSRF rejection (BUG-40/41/42)."""

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from mtg_analyzer import config
from mtg_analyzer.api.app import app

FOREIGN_ORIGIN = "http://attacker.example"
LOCAL_ORIGIN = "http://localhost:8765"


@pytest.fixture
def client():
    return TestClient(app)


def test_foreign_host_is_rejected(client):
    assert client.get("/api/health", headers={"Host": "attacker.example"}).status_code == 400
    assert client.get("/api/health", headers={"Host": "attacker.example:8000"}).status_code == 400


@pytest.mark.parametrize("host", ["localhost:8000", "127.0.0.1:8000", "[::1]:8000", "testserver"])
def test_allowed_hosts_pass(client, host):
    assert client.get("/api/health", headers={"Host": host}).status_code == 200


def test_lan_ip_rejected_without_host_flag_and_allowed_with_it(client, monkeypatch):
    assert client.get("/api/health", headers={"Host": "192.168.1.5:8000"}).status_code == 400
    monkeypatch.setattr(config, "BIND_HOST", "192.168.1.5")
    assert client.get("/api/health", headers={"Host": "192.168.1.5:8000"}).status_code == 200
    assert client.get("/api/health", headers={"Host": "attacker.example"}).status_code == 400
    monkeypatch.setattr(config, "BIND_HOST", "0.0.0.0")
    assert client.get("/api/health", headers={"Host": "10.0.0.7:8000"}).status_code == 200
    assert client.get("/api/health", headers={"Host": "attacker.example"}).status_code == 400


def test_websocket_foreign_origin_closed_1008(client):
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws/lobby?name=Ann", headers={"Origin": FOREIGN_ORIGIN}):
            pass
    assert exc.value.code == 1008


def test_websocket_foreign_host_closed_1008(client):
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws/lobby?name=Ann", headers={"Host": "attacker.example"}):
            pass
    assert exc.value.code == 1008


@pytest.mark.parametrize("origin", [LOCAL_ORIGIN, "http://127.0.0.1:8000", None])
def test_websocket_allowed_or_absent_origin_connects(client, origin):
    headers = {"Origin": origin} if origin else {}
    with client.websocket_connect("/ws/lobby?name=Ann", headers=headers) as socket:
        assert socket.receive_json()


UNSAFE_REQUESTS = {
    "multipart upload": ("post", "/api/players/Ann/sleeves", {"files": {"file": ("a.png", b"x", "image/png")}}),
    "bodyless post": ("post", "/api/cards/update", {}),
    "bodyless llm post": ("post", "/api/llm/test", {}),
    "json post": ("post", "/api/decks", {"json": {"cards": []}}),
    "delete": ("delete", "/api/saved-decks/nope", {}),
}


@pytest.mark.parametrize("name", UNSAFE_REQUESTS)
def test_unsafe_methods_with_foreign_origin_rejected(client, name):
    verb, path, kw = UNSAFE_REQUESTS[name]
    response = getattr(client, verb)(path, headers={"Origin": FOREIGN_ORIGIN}, **kw)
    assert response.status_code == 403
    # The guard answers before routing, so no job/download can have started.
    assert response.text.startswith("Rejected")


@pytest.mark.parametrize("name", UNSAFE_REQUESTS)
def test_unsafe_methods_cross_site_fetch_metadata_rejected(client, name):
    verb, path, kw = UNSAFE_REQUESTS[name]
    response = getattr(client, verb)(path, headers={"Sec-Fetch-Site": "cross-site"}, **kw)
    assert response.status_code == 403


@pytest.mark.parametrize("name", UNSAFE_REQUESTS)
def test_unsafe_methods_with_null_origin_rejected(client, name):
    verb, path, kw = UNSAFE_REQUESTS[name]
    assert getattr(client, verb)(path, headers={"Origin": "null"}, **kw).status_code == 403


@pytest.mark.parametrize("headers", [{}, {"Origin": LOCAL_ORIGIN}, {"Sec-Fetch-Site": "same-origin"}])
def test_unsafe_methods_from_allowed_or_non_browser_clients_reach_the_route(client, headers):
    # Non-browser (no Origin), local dev origin and same-origin browser pass the guard.
    response = client.post("/api/decks", json={"cards": []}, headers=headers)
    assert response.status_code != 403 or "Rejected" not in response.text


def test_get_with_foreign_origin_unaffected(client):
    assert client.get("/api/health", headers={"Origin": FOREIGN_ORIGIN}).status_code == 200


def test_same_origin_on_configured_lan_host_allowed(client, monkeypatch):
    monkeypatch.setattr(config, "BIND_HOST", "0.0.0.0")
    headers = {"Host": "192.168.1.5:8000", "Origin": "http://192.168.1.5:8000"}
    response = client.post("/api/decks", json={"cards": []}, headers=headers)
    assert "Rejected" not in response.text


def test_wildcard_bind_rejects_foreign_ip_origin(client, monkeypatch):
    monkeypatch.setattr(config, "BIND_HOST", "0.0.0.0")
    headers = {"Host": "192.168.1.5:8000", "Origin": "http://203.0.113.5"}
    assert client.post("/api/decks", json={"cards": []}, headers=headers).status_code == 403
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws/lobby?name=Ann", headers=headers):
            pass
    assert exc.value.code == 1008


def test_wildcard_bind_same_origin_lan_websocket_connects(client, monkeypatch):
    monkeypatch.setattr(config, "BIND_HOST", "0.0.0.0")
    headers = {"Host": "192.168.1.5:8000", "Origin": "http://192.168.1.5:8000"}
    with client.websocket_connect("/ws/lobby?name=Ann", headers=headers) as socket:
        assert socket.receive_json()
