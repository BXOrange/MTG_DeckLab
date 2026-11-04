"""PLR-16: sleeves, token art and favorites belong to the signed-in account (plan sections 1, 6).

Real sessions (`real_auth`): identity comes from the session, never from a URL name; foreign
assets look exactly like missing ones; anonymous callers get 401; deleting an account removes
its assets; legacy name-keyed rows are invisible until migrated.
"""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from mtg_analyzer.api import dependencies
from mtg_analyzer.api.app import app
from mtg_analyzer.api.auth import session_cookie_name
from mtg_analyzer.api.dependencies import get_account_store, get_player_asset_store
from mtg_analyzer.services.account_store import AccountStore
from mtg_analyzer.services.player_assets import PlayerAssetStore, bind_account_cleanup

pytestmark = pytest.mark.real_auth

MISSING_ID = "00000000-0000-0000-0000-000000000000"
PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 16
LEGACY_SCHEMA = """
CREATE TABLE token_images (player_name TEXT NOT NULL, token_name TEXT NOT NULL, content_type TEXT NOT NULL,
    data BLOB NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY (player_name, token_name));
CREATE TABLE sleeves (player_name TEXT NOT NULL, sleeve_id TEXT NOT NULL, label TEXT NOT NULL,
    content_type TEXT NOT NULL, data BLOB NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY (player_name, sleeve_id));
CREATE TABLE favorite_decks (player_name TEXT NOT NULL, deck_id TEXT NOT NULL, updated_at TEXT NOT NULL,
    PRIMARY KEY (player_name, deck_id));
"""


class _Actor:
    def __init__(self, client, uuid, csrf):
        self.client, self.uuid, self.csrf = client, uuid, csrf

    def call(self, method, url, **kw):
        headers = dict(kw.pop("headers", {}))
        if method.upper() not in ("GET", "HEAD") and self.csrf:
            headers["X-CSRF-Token"] = self.csrf
        return self.client.request(method, url, headers=headers, **kw)

    def get(self, url, **kw):
        return self.call("GET", url, **kw)

    def post(self, url, **kw):
        return self.call("POST", url, **kw)

    def delete(self, url, **kw):
        return self.call("DELETE", url, **kw)

    def upload_sleeve(self, label="Mine", data=PNG):
        return self.post("/api/me/sleeves", data={"label": label}, files={"file": ("a.png", data, "image/png")})


@pytest.fixture
def world(tmp_path):
    accounts = AccountStore(tmp_path / "accounts.db")
    assets = PlayerAssetStore(tmp_path / "assets.db")
    bind_account_cleanup(accounts, assets)
    app.dependency_overrides[get_account_store] = lambda: accounts
    app.dependency_overrides[get_player_asset_store] = lambda: assets

    def actor(name):
        account = accounts.create_account_unchecked(name, "!", "player")
        token, session = accounts.create_session(account.player_uuid)
        client = TestClient(app)
        client.cookies.set(session_cookie_name(), token)
        return _Actor(client, account.player_uuid, session.csrf_token)

    yield {
        "alice": actor("Alice"), "bob": actor("Bob"), "anon": _Actor(TestClient(app), None, ""),
        "accounts": accounts, "assets": assets,
    }
    app.dependency_overrides.pop(get_account_store, None)
    app.dependency_overrides.pop(get_player_asset_store, None)
    accounts.close()
    assets.close()


ROUTES = [
    ("get", "/api/me/sleeves"),
    ("get", "/api/me/token-images"),
    ("get", "/api/me/favorite-decks"),
    ("get", "/api/me/sleeves/x/image"),
    ("get", "/api/me/token-images/image?token_name=t"),
    ("delete", "/api/me/sleeves/x"),
    ("delete", "/api/me/token-images?token_name=t"),
    ("delete", "/api/me/favorite-decks/d"),
]


@pytest.mark.parametrize("method,url", ROUTES)
def test_anonymous_gets_401_everywhere(world, method, url):
    assert getattr(world["anon"], method)(url).status_code == 401


def test_anonymous_writes_are_401(world):
    anon = world["anon"]
    assert anon.upload_sleeve().status_code == 401
    assert anon.post("/api/me/token-images", data={"token_name": "t"}, files={"file": ("a.png", PNG, "image/png")}).status_code == 401
    assert anon.post("/api/me/favorite-decks", json={"deckId": "d"}).status_code == 401
    assert world["assets"].count_for_owner("") == {"token_images": 0, "sleeves": 0, "favorite_decks": 0}


def test_upload_is_owned_by_the_session_account_and_visible_to_it(world):
    alice = world["alice"]
    created = alice.upload_sleeve("Back")
    assert created.status_code == 200
    sleeve_id = created.json()["sleeve_id"]
    assert [s["label"] for s in alice.get("/api/me/sleeves").json()] == ["Back"]
    image = alice.get(f"/api/me/sleeves/{sleeve_id}/image")
    assert image.status_code == 200 and image.content == PNG
    assert world["assets"].count_for_owner(alice.uuid)["sleeves"] == 1


def test_foreign_assets_look_exactly_like_missing_ones(world):
    alice, bob = world["alice"], world["bob"]
    sleeve_id = alice.upload_sleeve().json()["sleeve_id"]
    alice.post("/api/me/token-images", data={"token_name": "Soldier"}, files={"file": ("a.png", PNG, "image/png")})
    alice.post("/api/me/favorite-decks", json={"deckId": "deck-1"})

    foreign = bob.get(f"/api/me/sleeves/{sleeve_id}/image")
    missing = bob.get(f"/api/me/sleeves/{MISSING_ID}/image")
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json()["detail"]["code"] == missing.json()["detail"]["code"] == "sleeve_not_found"
    assert foreign.json()["detail"]["message"].replace(sleeve_id, "X") == missing.json()["detail"]["message"].replace(MISSING_ID, "X")
    assert bob.get("/api/me/token-images/image?token_name=Soldier").status_code == 404
    assert bob.get("/api/me/sleeves").json() == []
    assert bob.get("/api/me/token-images").json() == []
    assert bob.get("/api/me/favorite-decks").json() == []  # favorites are private


def test_second_account_cannot_delete_or_overwrite(world):
    alice, bob = world["alice"], world["bob"]
    sleeve_id = alice.upload_sleeve().json()["sleeve_id"]
    alice.post("/api/me/token-images", data={"token_name": "Soldier"}, files={"file": ("a.png", PNG, "image/png")})
    alice.post("/api/me/favorite-decks", json={"deckId": "deck-1"})
    assert bob.delete(f"/api/me/sleeves/{sleeve_id}").status_code == 404
    assert bob.delete("/api/me/token-images?token_name=Soldier").status_code == 404
    bob.delete("/api/me/favorite-decks/deck-1")  # idempotent no-op for bob
    bob.post("/api/me/token-images", data={"token_name": "Soldier"}, files={"file": ("a.png", PNG + b"2", "image/png")})
    assert alice.get(f"/api/me/sleeves/{sleeve_id}/image").status_code == 200
    assert alice.get("/api/me/token-images/image?token_name=Soldier").content == PNG
    assert alice.get("/api/me/favorite-decks").json() == ["deck-1"]


@pytest.mark.parametrize("path", ["/api/players/Alice/sleeves", "/api/players/Bob/favorite-decks"])
def test_name_in_url_routes_no_longer_exist(world, path):
    """A URL name can never select an account's assets: the old name-keyed routes are gone."""
    alice = world["alice"]
    alice.upload_sleeve()
    assert world["bob"].get(path).status_code == 404
    assert world["anon"].get(path).status_code in (404, 405)


def test_name_in_query_or_form_is_ignored(world):
    alice, bob = world["alice"], world["bob"]
    alice.upload_sleeve()
    assert bob.get("/api/me/sleeves?player_name=Alice&owner_uuid=" + alice.uuid).json() == []
    res = bob.post("/api/me/sleeves", data={"label": "x", "player_name": "Alice", "owner_uuid": alice.uuid},
                   files={"file": ("a.png", PNG, "image/png")})
    assert res.status_code == 200
    assert len(alice.get("/api/me/sleeves").json()) == 1 and len(bob.get("/api/me/sleeves").json()) == 1


def test_writes_need_the_csrf_header(world):
    alice = world["alice"]
    alice.csrf = ""
    assert alice.upload_sleeve().status_code == 403
    assert alice.post("/api/me/favorite-decks", json={"deckId": "d"}).status_code == 403


def test_rename_does_not_change_ownership(world):
    alice = world["alice"]
    sleeve_id = alice.upload_sleeve().json()["sleeve_id"]
    accounts = world["accounts"]
    accounts._conn.execute("UPDATE accounts SET name = 'Alicia', name_norm = 'alicia' WHERE player_uuid = ?", (alice.uuid,))
    assert alice.get(f"/api/me/sleeves/{sleeve_id}/image").status_code == 200
    squatter = accounts.create_account_unchecked("Alice", "!", "player")  # the freed name goes to someone else
    token, session = accounts.create_session(squatter.player_uuid)
    other = _Actor(TestClient(app), squatter.player_uuid, session.csrf_token)
    other.client.cookies.set(session_cookie_name(), token)
    assert other.get("/api/me/sleeves").json() == []


def test_no_cross_seat_read_in_a_shared_game(world):
    """The board only ever loads the local player's own art (an opponent's hand backs use *your* sleeve),
    so another seat's asset is never fetched by id: it is a 404 even when both sit at one table."""
    alice, bob = world["alice"], world["bob"]
    sleeve_id = alice.upload_sleeve().json()["sleeve_id"]
    assert bob.get(f"/api/me/sleeves/{sleeve_id}/image").status_code == 404


def test_legacy_rows_are_invisible_to_the_runtime(tmp_path):
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    conn.executescript(LEGACY_SCHEMA)
    conn.execute("INSERT INTO sleeves VALUES ('Alice', 's1', 'Old', 'image/png', x'89504e47', '2024')")
    conn.execute("INSERT INTO favorite_decks VALUES ('Alice', 'deck-1', '2024')")
    conn.commit()
    conn.close()
    with PlayerAssetStore(path) as store:
        assert store.schema_version == 1
        for who in ("Alice", "alice", "", "any-uuid"):
            assert store.list_sleeves(who) == [] and store.get_sleeve(who, "s1") is None
            assert store.list_favorite_decks(who) == []
        assert store.delete_all_for_owner("") == 0 and store.purge_orphans([]) == 0
        row = sqlite3.connect(path).execute("SELECT legacy_name, owner_uuid, label FROM sleeves").fetchone()
        assert row == ("Alice", None, "Old")  # kept, unassigned


def test_schema_enforces_an_owner_or_a_legacy_name(tmp_path):
    with PlayerAssetStore(tmp_path / "s.db") as store:
        with pytest.raises(sqlite3.IntegrityError):
            store._connection.execute(
                "INSERT INTO favorite_decks (owner_uuid, legacy_name, deck_id, updated_at) VALUES (NULL, NULL, 'd', 'now')"
            )


def test_migration_is_idempotent_and_reopen_safe(tmp_path):
    path = tmp_path / "s.db"
    with PlayerAssetStore(path) as store:
        store.add_favorite_deck("u1", "d")
    with PlayerAssetStore(path) as store:
        assert store.list_favorite_decks("u1") == ["d"] and store.schema_version == 1


# -- cleanup (account delete) ---------------------------------------------------------------


def test_deleting_an_account_removes_its_assets_only(world):
    alice, bob, accounts, assets = world["alice"], world["bob"], world["accounts"], world["assets"]
    alice.upload_sleeve()
    alice.post("/api/me/favorite-decks", json={"deckId": "d"})
    bob.upload_sleeve()
    assert assets.count_for_owner(alice.uuid) == {"token_images": 0, "sleeves": 1, "favorite_decks": 1}
    accounts.delete_account(alice.uuid)
    assert assets.count_for_owner(alice.uuid) == {"token_images": 0, "sleeves": 0, "favorite_decks": 0}
    assert assets.count_for_owner(bob.uuid)["sleeves"] == 1


def test_disabling_keeps_assets_so_it_stays_reversible(world):
    alice = world["alice"]
    alice.upload_sleeve()
    world["accounts"].set_disabled(alice.uuid, True)
    assert world["assets"].count_for_owner(alice.uuid)["sleeves"] == 1


def test_purge_orphans_keeps_live_owners_and_legacy_rows(world):
    assets = world["assets"]
    assets.add_favorite_deck("live", "d")
    assets.add_favorite_deck("gone", "d")
    assert assets.purge_orphans(["live"]) == 1
    assert assets.list_favorite_decks("live") == ["d"] and assets.list_favorite_decks("gone") == []


def test_real_dependency_wiring_binds_cleanup(tmp_path, monkeypatch):
    monkeypatch.setattr(dependencies, "ACCOUNTS_DB_PATH", tmp_path / "accounts.db")
    monkeypatch.setattr(dependencies, "PLAYER_ASSETS_DB_PATH", tmp_path / "assets.db")
    dependencies._account_store.cache_clear()
    dependencies._player_asset_store.cache_clear()
    try:
        accounts = dependencies.get_account_store()
        assets = dependencies.get_player_asset_store()
        account = accounts.create_account_unchecked("Carol", "!", "player")
        assets.add_favorite_deck(account.player_uuid, "d")
        accounts.delete_account(account.player_uuid)
        assert assets.list_favorite_decks(account.player_uuid) == []
    finally:
        dependencies.get_account_store().close()
        dependencies.get_player_asset_store().close()
        dependencies._account_store.cache_clear()
        dependencies._player_asset_store.cache_clear()
