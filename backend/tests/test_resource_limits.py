"""BUG-43: bounded sessions, lobby, uploads and bug-report storage."""
import asyncio
import gzip

import pytest
from fastapi.testclient import TestClient

from mtg_analyzer import config
from mtg_analyzer.api import player_assets as player_assets_api
from mtg_analyzer.api.app import app
from mtg_analyzer.api.dependencies import get_game_session_manager, get_player_asset_store
from mtg_analyzer.api.multiplayer_ws import sweep_once
from mtg_analyzer.services import lobby as lobby_module
from mtg_analyzer.services import player_assets as assets_module
from mtg_analyzer.services.game_session import GameSessionManager
from mtg_analyzer.services.lobby import Lobby, LobbyError
from mtg_analyzer.services.player_assets import AssetQuotaError, PlayerAssetStore
from mtg_analyzer.services.replay import blank_replay


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def _manager(clock, ttl=100.0, cap=3):
    return GameSessionManager(ttl_seconds=ttl, max_sessions=cap, clock=clock)


def _replay(manager):
    return manager.create_replay(blank_replay(), loader=None)


# -- sessions ---------------------------------------------------------------


def test_session_expires_after_ttl_without_access():
    clock = _Clock()
    manager = _manager(clock)
    session = _replay(manager)
    clock.now += 99
    assert manager.sweep() == 0
    clock.now += 2
    assert manager.sweep() == 1
    with pytest.raises(KeyError):
        manager.get(session.id)


def test_get_counts_as_access_and_resets_ttl():
    clock = _Clock()
    manager = _manager(clock)
    session = _replay(manager)
    clock.now += 90
    manager.get(session.id)
    clock.now += 90
    assert manager.sweep() == 0
    assert manager.get(session.id) is session


def test_lru_eviction_past_cap_drops_least_recently_used():
    clock = _Clock()
    manager = _manager(clock, cap=3)
    first, second, third = (_replay(manager) for _ in range(3))
    clock.now += 1
    manager.get(first.id)  # second is now the least recently used
    clock.now += 1
    fourth = _replay(manager)
    assert len(manager) == 3
    with pytest.raises(KeyError):
        manager.get(second.id)
    for kept in (first, third, fourth):
        assert manager.get(kept.id) is kept


def test_protected_session_survives_ttl_and_lru():
    clock = _Clock()
    manager = _manager(clock, cap=2)
    table = _replay(manager)
    manager.set_protected_provider(lambda: {table.id})
    others = [_replay(manager) for _ in range(3)]
    assert manager.get(table.id) is table  # never the LRU victim
    clock.now += 10_000
    manager.sweep()
    assert manager.get(table.id) is table
    for gone in others[:-1]:
        with pytest.raises(KeyError):
            manager.get(gone.id)


def test_dependency_manager_protects_lobby_table_sessions():
    from mtg_analyzer.api.dependencies import _game_session_manager, _lobby

    manager, lobby = _game_session_manager(), _lobby()
    session = manager.create_replay(blank_replay(), loader=None)
    player = lobby.connect("Zed")
    game = lobby.create(player.id)
    game.session_id = session.id
    try:
        assert session.id in manager._protected()
    finally:
        game.session_id = None
        lobby.disconnect(player.id)
        manager.remove(session.id)


def test_sweep_once_runs_session_sweep():
    clock = _Clock()
    manager = _manager(clock)
    session = _replay(manager)
    clock.now += 500
    asyncio.run(sweep_once(Lobby(), manager))
    with pytest.raises(KeyError):
        manager.get(session.id)


# -- lobby ------------------------------------------------------------------


def test_lobby_refuses_players_past_cap_but_reclaims_existing(monkeypatch):
    monkeypatch.setattr(lobby_module, "LOBBY_MAX_PLAYERS", 2)
    lobby = Lobby()
    lobby.connect("A", client_token="ta")
    lobby.connect("B", client_token="tb")
    with pytest.raises(LobbyError):
        lobby.connect("C", client_token="tc")
    assert lobby.connect("A", client_token="ta").name == "A"  # reclaim is not a new player


def test_lobby_cap_ignores_bots(monkeypatch):
    monkeypatch.setattr(lobby_module, "LOBBY_MAX_PLAYERS", 2)
    lobby = Lobby()
    host = lobby.connect("A", client_token="ta")
    game = lobby.create(host.id)
    lobby.add_bot(game.id, host.id, "greedy")
    lobby.connect("B", client_token="tb")


def test_lobby_refuses_tables_past_cap(monkeypatch):
    monkeypatch.setattr(lobby_module, "LOBBY_MAX_GAMES", 1)
    lobby = Lobby()
    a, b = lobby.connect("A"), lobby.connect("B")
    lobby.create(a.id)
    with pytest.raises(LobbyError):
        lobby.create(b.id)


def test_connect_route_returns_400_when_lobby_full(monkeypatch):
    monkeypatch.setattr(lobby_module, "LOBBY_MAX_PLAYERS", 1)
    lobby = Lobby()
    from mtg_analyzer.api.dependencies import get_lobby

    app.dependency_overrides[get_lobby] = lambda: lobby
    try:
        client = TestClient(app)
        assert client.post("/api/multiplayer/connect", json={"name": "A"}).status_code == 200
        response = client.post("/api/multiplayer/connect", json={"name": "B"})
        assert response.status_code == 400
    finally:
        app.dependency_overrides.pop(get_lobby, None)


# -- uploads ----------------------------------------------------------------


@pytest.fixture
def asset_client():
    store = PlayerAssetStore(":memory:")
    app.dependency_overrides[get_player_asset_store] = lambda: store
    try:
        yield TestClient(app), store
    finally:
        app.dependency_overrides.pop(get_player_asset_store, None)
        store.close()


PNG_MAGIC = b"\x89PNG\r\n\x1a\n"  # BUG-44: uploads must carry the declared type's signature


def _png(size):
    return PNG_MAGIC + b"x" * (size - len(PNG_MAGIC))


def _upload(client, data, label="x"):
    return client.post(
        "/api/players/Ann/sleeves",
        data={"label": label},
        files={"file": ("a.png", data, "image/png")},
    )


def test_oversized_upload_is_413(asset_client, monkeypatch):
    client, _ = asset_client
    monkeypatch.setattr(player_assets_api, "_MAX_UPLOAD_BYTES", 1024)
    assert _upload(client, _png(1024)).status_code == 200
    assert _upload(client, _png(1025)).status_code == 413


def test_upload_read_aborts_without_consuming_whole_body(monkeypatch):
    monkeypatch.setattr(player_assets_api, "_MAX_UPLOAD_BYTES", 100)
    monkeypatch.setattr(config, "UPLOAD_READ_CHUNK_BYTES", 40)

    class _Upload:
        content_type = "image/png"
        reads = 0

        async def read(self, size=-1):
            assert size > 0, "must read in bounded chunks"
            self.reads += 1
            return b"x" * size

    upload = _Upload()
    with pytest.raises(player_assets_api.HTTPException) as caught:
        asyncio.run(player_assets_api._read_validated_image(upload))
    assert caught.value.status_code == 413
    assert upload.reads == 3  # 40+40+40 crosses 100; the rest is never read


def test_per_name_count_quota(asset_client, monkeypatch):
    client, store = asset_client
    monkeypatch.setattr(assets_module, "PLAYER_ASSET_MAX_COUNT", 2)
    assert _upload(client, _png(16), "1").status_code == 200
    assert _upload(client, _png(16), "2").status_code == 200
    assert _upload(client, _png(16), "3").status_code == 413
    # Another name is unaffected, and replacing an existing token image still works.
    other = client.post(
        "/api/players/Bob/sleeves", data={"label": "1"}, files={"file": ("a.png", _png(16), "image/png")}
    )
    assert other.status_code == 200
    store.save_token_image("Bob", "t", "image/png", b"1")
    store.save_token_image("Bob", "t", "image/png", b"2")


def test_per_name_byte_quota(monkeypatch):
    monkeypatch.setattr(assets_module, "PLAYER_ASSET_MAX_TOTAL_BYTES", 10)
    with PlayerAssetStore(":memory:") as store:
        store.save_token_image("Ann", "t", "image/png", b"x" * 8)
        with pytest.raises(AssetQuotaError):
            store.save_sleeve("Ann", "s", "l", "image/png", b"x" * 3)
        store.save_token_image("Ann", "t", "image/png", b"x" * 10)  # replace: net growth only


# -- bug reports ------------------------------------------------------------


def test_bug_report_cap_refuses_and_keeps_existing(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BUG_REPORT_DIR", tmp_path)
    monkeypatch.setattr(config, "BUG_REPORT_MAX_COUNT", 2)
    app.dependency_overrides[get_game_session_manager] = lambda: GameSessionManager()
    try:
        client = TestClient(app)
        for _ in range(2):
            assert client.post("/api/bug-reports", json={"description": "x"}).status_code == 201
        before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
        assert client.post("/api/bug-reports", json={"description": "y"}).status_code == 507
        assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before
    finally:
        app.dependency_overrides.pop(get_game_session_manager, None)


def test_bug_report_byte_cap_refuses(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BUG_REPORT_DIR", tmp_path)
    monkeypatch.setattr(config, "BUG_REPORT_MAX_TOTAL_BYTES", 1)
    (tmp_path / "old.json.gz").write_bytes(gzip.compress(b"{}"))
    client = TestClient(app)
    assert client.post("/api/bug-reports", json={"description": "y"}).status_code == 507
    assert (tmp_path / "old.json.gz").exists()


# -- follow-ups: early Content-Length guard, global store cap, WS lobby-full --


def test_oversized_content_length_rejected_before_store_or_form(asset_client, monkeypatch):
    client, store = asset_client
    monkeypatch.setattr(player_assets_api, "_MAX_UPLOAD_BYTES", 1024)
    monkeypatch.setattr(config, "UPLOAD_MULTIPART_OVERHEAD_BYTES", 100)

    def _boom(*args, **kwargs):
        raise AssertionError("store reached")

    monkeypatch.setattr(store, "save_sleeve", _boom)
    reads = []

    async def _no_read(self, *a, **k):
        reads.append(1)
        raise AssertionError("form parsed")

    monkeypatch.setattr("starlette.requests.Request.form", _no_read)
    response = client.post(
        "/api/players/Ann/sleeves",
        content=b"x" * 5000,
        headers={"content-type": "multipart/form-data; boundary=b"},
    )
    assert response.status_code == 413
    assert not reads


def test_global_store_byte_cap_defeats_name_rotation(monkeypatch):
    monkeypatch.setattr(assets_module, "PLAYER_ASSET_STORE_MAX_BYTES", 10)
    with PlayerAssetStore(":memory:") as store:
        store.save_sleeve("A", "s1", "l", "image/png", b"x" * 6)
        with pytest.raises(AssetQuotaError):
            store.save_sleeve("B", "s2", "l", "image/png", b"x" * 6)
        store.save_sleeve("B", "s2", "l", "image/png", b"x" * 4)


def test_ws_lobby_full_sends_reason_and_closes(monkeypatch):
    from mtg_analyzer.api.dependencies import get_lobby

    monkeypatch.setattr(lobby_module, "LOBBY_MAX_PLAYERS", 1)
    lobby = Lobby()
    lobby.connect("A")
    app.dependency_overrides[get_lobby] = lambda: lobby
    try:
        client = TestClient(app)
        with client.websocket_connect("/ws/lobby?name=B") as ws:
            message = ws.receive_json()
        assert message["type"] == "disconnected"
        assert message["reason"] == "lobby_full"
    finally:
        app.dependency_overrides.pop(get_lobby, None)
