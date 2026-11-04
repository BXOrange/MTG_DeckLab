"""PLR-9d / PLR-17: /api/admin, initial setup, admin invitations, update-route enforcement.

Reference: docs/concepts/15_ACCOUNT_SYSTEM_PLAN.md section 6 and the section 8 gates *Admin*,
*Initial setup*, *Admin invitations*. Every store is a throwaway one (tmp_path / memory): nothing
here touches ``data/*.db``.
"""

import base64
import time

import pytest
from fastapi.testclient import TestClient

from mtg_analyzer import config
from mtg_analyzer.api.admin_auth import get_admin_limiter
from mtg_analyzer.api.app import app
from mtg_analyzer.api.auth import get_login_limiter, get_password_hasher, get_signup_limiter
from mtg_analyzer.api.dependencies import (
    get_account_store, get_admin_jobs, get_deck_database, get_game_session_manager, get_player_asset_store,
)
from mtg_analyzer.models.decks.deck import Deck
from mtg_analyzer.services import account_store as acc
from mtg_analyzer.services.account_store import AccountStore
from mtg_analyzer.services.admin_jobs import AdminJobs
from mtg_analyzer.services.deck_database import DeckDatabase
from mtg_analyzer.services.game_session import GameSessionManager
from mtg_analyzer.services.password_hasher import PasswordHasher
from mtg_analyzer.services.player_assets import PlayerAssetStore, bind_account_cleanup
from mtg_analyzer.services.rate_limiter import FailureLimiter

pytestmark = pytest.mark.real_auth

FAST = PasswordHasher(n=2 ** 4)
ADMIN_PW = "a-long-admin-passphrase-1"  # 25 characters
PLAYER_PW = "player pass 9!"
THROTTLE_LIMIT = 5
LOCAL = dict(base_url="http://localhost", client=("127.0.0.1", 50000))


def api_routes():
    """Every route of the app, flattened out of the included routers (APIRoute: path, methods, dependant)."""
    found = []
    for route in app.routes:
        nested = getattr(route, "original_router", None)
        found.extend(nested.routes if nested is not None else [route])
    return [r for r in found if hasattr(r, "path")]


def _returning(value):
    return lambda: value


@pytest.fixture
def env(tmp_path):
    store = AccountStore(tmp_path / "accounts.db")
    decks = DeckDatabase(":memory:")
    assets = PlayerAssetStore(":memory:")
    bind_account_cleanup(store, assets)
    sessions = GameSessionManager()
    finished = []
    jobs = AdminJobs(runners={
        "card-pool": lambda report: (report("lade"), {"updated": True})[1],
        "combos": lambda report: {"summary": {}},
    })
    limiters = {
        get_admin_limiter: FailureLimiter(THROTTLE_LIMIT, 60.0),
        get_login_limiter: FailureLimiter(50, 60.0),
        get_signup_limiter: FailureLimiter(50, 60.0),
    }
    overrides = {
        get_account_store: lambda: store, get_deck_database: lambda: decks,
        get_player_asset_store: lambda: assets, get_game_session_manager: lambda: sessions,
        get_admin_jobs: lambda: jobs, get_password_hasher: lambda: FAST,
        **{dep: _returning(lim) for dep, lim in limiters.items()},
    }
    app.dependency_overrides.update(overrides)
    yield {"store": store, "decks": decks, "assets": assets, "sessions": sessions, "jobs": jobs, "finished": finished}
    for dep in overrides:
        app.dependency_overrides.pop(dep, None)
    store.close()


@pytest.fixture
def client(env):
    return TestClient(app, **LOCAL)


def basic(name, password):
    raw = f"{name}:{password}".encode("utf-8")
    return {"Authorization": "Basic " + base64.b64encode(raw).decode()}


def make_admin(env, name="boss", password=ADMIN_PW):
    return env["store"].create_account_unchecked(name, FAST.hash(password), acc.ROLE_ADMIN)


def admin_headers(env, name="boss", password=ADMIN_PW):
    if env["store"].get_by_name(name) is None:
        make_admin(env, name, password)
    return basic(name, password)


def make_player(env, name="Alice", password=PLAYER_PW):
    store = env["store"]
    token = store.create_invitation(acc.OPERATOR_CREATOR, acc.ROLE_PLAYER, enforce_limits=False)
    return store.create_account_with_invitation(name, FAST.hash(password), token, acc.ROLE_PLAYER)


def player_login(env, name="Alice", password=PLAYER_PW):
    """A signed-in player's client (real cookie + CSRF header)."""
    client = TestClient(app, **LOCAL)
    r = client.post("/api/auth/login", json={"name": name, "password": password})
    assert r.status_code == 200
    client.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    return client


# ---------------------------------------------------------------------------
# Gate: loopback only, no cookie, per-request credentials
# ---------------------------------------------------------------------------

class TestSurfaceGate:
    def test_state_is_reachable_locally(self, client):
        assert client.get("/api/admin/state").status_code == 200

    @pytest.mark.parametrize("peer", ["192.168.1.7", "10.0.0.2", "::ffff:192.168.1.7"])
    def test_a_lan_client_gets_403_on_every_admin_route(self, env, peer):
        lan = TestClient(app, base_url="http://localhost", client=(peer, 50000))
        headers = admin_headers(env)
        for method, path in (("get", "/api/admin/state"), ("get", "/api/admin/players"),
                             ("post", "/api/admin/jobs"), ("get", "/api/admin/audit"),
                             ("post", "/api/admin/signup")):
            r = getattr(lan, method)(path, headers=headers)
            assert r.status_code == 403, path
            assert r.json()["detail"]["code"] == "admin_local_only"

    def test_forwarding_headers_make_a_loopback_peer_non_local(self, client, env):
        r = client.get("/api/admin/players", headers={**admin_headers(env), "X-Forwarded-For": "192.168.1.7"})
        assert r.status_code == 403

    def test_a_non_loopback_host_is_not_local(self, env):
        assert TestClient(app, base_url="http://localhost", client=("127.0.0.1", 1)).get(
            "/api/admin/state", headers={"Host": "192.168.1.5"}).status_code in (400, 403)

    def test_no_cookie_is_ever_set_and_responses_are_not_cacheable(self, client, env):
        r = client.get("/api/admin/whoami", headers=admin_headers(env))
        assert r.status_code == 200 and r.json()["name"] == "boss"
        assert "set-cookie" not in r.headers and not client.cookies
        assert r.headers["cache-control"] == "no-store"
        assert env["store"].list_sessions(env["store"].get_by_name("boss").player_uuid) == []

    def test_a_read_needs_credentials_every_time(self, client, env):
        admin_headers(env)
        assert client.get("/api/admin/players", headers=basic("boss", ADMIN_PW)).status_code == 200
        assert client.get("/api/admin/players").status_code == 401  # nothing remembered server-side

    def test_unicode_passwords_work(self, client, env):
        pw = "pässwörd-日本語-ünïcode-1234"
        make_admin(env, "uni", pw)
        assert client.get("/api/admin/whoami", headers=basic("uni", pw)).status_code == 200


class TestAuthentication:
    def test_failures_are_generic(self, client, env):
        make_admin(env, "boss")
        make_player(env, "Alice")
        disabled = make_admin(env, "gone")
        env["store"]._conn.execute("UPDATE accounts SET disabled = 1 WHERE player_uuid = ?", (disabled.player_uuid,))
        seen = set()
        for creds in (basic("boss", "wrong-password-xxxxxxx"), basic("nobody", ADMIN_PW),
                      basic("Alice", PLAYER_PW), basic("gone", ADMIN_PW), basic("local", "x"), {}):
            r = client.get("/api/admin/whoami", headers=creds)
            seen.add((r.status_code, r.json()["detail"]["code"]))
        assert seen == {(401, "admin_auth_required")}

    def test_throttled_by_admin_identity_not_source(self, client, env):
        make_admin(env, "boss")
        for _ in range(THROTTLE_LIMIT):
            assert client.get("/api/admin/whoami", headers=basic("boss", "wrong-password-xxxxxxx")).status_code == 401
        r = client.get("/api/admin/whoami", headers=basic("boss", ADMIN_PW))
        assert r.status_code == 429 and "retry-after" in r.headers
        # Another identity from the very same loopback source is unaffected.
        make_admin(env, "other", ADMIN_PW)
        assert client.get("/api/admin/whoami", headers=basic("other", ADMIN_PW)).status_code == 200

    def test_failed_attempts_against_a_real_admin_are_audited_without_the_password(self, client, env):
        make_admin(env, "boss")
        client.get("/api/admin/whoami", headers=basic("boss", "hunter2-hunter2-hunter2"))
        client.get("/api/admin/whoami", headers=basic("nobody", "x"))  # unknown names are not logged
        entries, _ = env["store"].list_audit(limit=10)
        assert [(e["actor"], e["action"], e["result"]) for e in entries] == [("boss", "admin.auth", "denied")]
        assert "hunter2" not in repr(entries)

    def test_player_cookie_session_is_not_accepted(self, env):
        make_player(env)
        player = player_login(env)
        assert player.cookies
        for method, path in (("get", "/api/admin/players"), ("get", "/api/admin/audit"),
                             ("get", "/api/admin/whoami"), ("get", "/api/admin/decks")):
            assert getattr(player, method)(path).status_code == 401, path
        assert player.post("/api/admin/jobs", json={"kind": "card-pool"}).status_code == 401

    def test_players_with_their_own_password_are_refused(self, client, env):
        make_player(env)
        for path in ("/api/admin/players", "/api/admin/audit", "/api/admin/decks", "/api/admin/invitations"):
            assert client.get(path, headers=basic("Alice", PLAYER_PW)).status_code == 401

    def test_anonymous_fails_on_every_admin_route(self, client):
        routes = [r for r in api_routes() if r.path.startswith("/api/admin/")]
        assert routes
        skip = {"/api/admin/state", "/api/admin/signup", "/api/admin/recover"}  # credential-bearing bodies
        for route in routes:
            if route.path in skip:
                continue
            path = route.path.replace("{player_uuid}", "x").replace("{deck_id}", "x").replace(
                "{invitation_id}", "x").replace("{job_id}", "x")
            for method in route.methods - {"HEAD", "OPTIONS"}:
                r = client.request(method, path, json={} if method not in ("GET", "DELETE") else None)
                assert r.status_code == 401, (method, route.path)

    def test_admin_credentials_do_not_log_into_the_player_ui(self, client, env):
        make_admin(env)
        r = client.post("/api/auth/login", json={"name": "boss", "password": ADMIN_PW})
        assert r.status_code == 401
        assert client.get("/api/auth/me").json() == {"authenticated": False}

    def test_admin_credentials_reach_no_player_route(self, client, env):
        headers = admin_headers(env)
        for method, path in (("get", "/api/me/sleeves"), ("post", "/api/solo/start"),
                             ("post", "/api/game/goldfish")):
            assert getattr(client, method)(path, headers=headers).status_code in (401, 404, 405, 422), path
        # PLR-18: the deck list is public (global decks), but an admin credential is not a player.
        assert client.post("/api/decks/save", json={"name": "x"}, headers=headers).status_code == 401

    def test_admin_cannot_use_the_player_signup(self, client, env):
        token = env["store"].create_invitation(acc.OPERATOR_CREATOR, acc.ROLE_ADMIN, enforce_limits=False)
        r = client.post("/api/auth/signup", json={"name": "Mallory", "password": PLAYER_PW, "invitation": token})
        assert r.status_code == 400 and r.json()["detail"]["code"] == "invalid_invitation"
        r = client.post("/api/auth/signup", json={"name": "x", "password": PLAYER_PW, "invitation": "t", "role": "admin"})
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# Initial setup
# ---------------------------------------------------------------------------

class TestInitialSetup:
    @pytest.fixture
    def seeded(self, env):
        env["store"].seed_initial_admin(FAST.hash(acc.INITIAL_ADMIN_PASSWORD))
        return env

    def initial(self):
        return basic(acc.INITIAL_ADMIN_NAME, acc.INITIAL_ADMIN_PASSWORD)

    def test_state_reports_setup_open(self, client, seeded):
        assert client.get("/api/admin/state").json()["setup_open"] is True

    def test_before_the_change_only_setup_works(self, client, seeded):
        h = self.initial()
        for method, path in (("get", "/api/admin/whoami"), ("get", "/api/admin/players"),
                             ("get", "/api/admin/invitations"), ("post", "/api/admin/invitations"),
                             ("get", "/api/admin/audit"), ("get", "/api/admin/decks"), ("get", "/api/admin/jobs"),
                             ("post", "/api/admin/jobs")):
            r = getattr(client, method)(path, headers=h)
            assert r.status_code == 403 and r.json()["detail"]["code"] == "setup_required", path

    def test_update_routes_refuse_the_initial_credential(self, client, seeded):
        assert client.post("/api/cards/update", headers=self.initial()).status_code == 403
        assert client.post("/api/combos/update", headers=self.initial()).status_code == 403

    def test_player_operations_are_refused_with_the_initial_credential(self, client, seeded):
        assert client.post("/api/decks/save", json={"name": "x"}, headers=self.initial()).status_code == 401  # PLR-18: reads are public
        assert client.post("/api/auth/login", json={"name": "admin", "password": "admin"}).status_code == 401

    def test_14_characters_rejected_15_accepted(self, client, seeded):
        r = client.post("/api/admin/setup", headers=self.initial(), json={"new_password": "a1b2c3d4e5f6g7"})
        assert len("a1b2c3d4e5f6g7") == 14 and r.status_code == 400
        assert r.json()["detail"]["code"] == "password_too_short"
        assert client.get("/api/admin/state").json()["setup_open"] is True
        ok = "a1b2c3d4e5f6g7h"
        assert len(ok) == 15
        assert client.post("/api/admin/setup", headers=self.initial(), json={"new_password": ok}).status_code == 200

    @pytest.mark.parametrize("weak", ["aaaaaaaaaaaaaaaa", "abcdefghijklmnop", "admin", "password1234567"])
    def test_blocklisted_and_trivial_passwords_are_refused(self, client, seeded, weak):
        assert client.post("/api/admin/setup", headers=self.initial(), json={"new_password": weak}).status_code == 400

    def test_the_initial_password_cannot_be_reused(self, client, seeded, monkeypatch):
        # Even with the length floor lowered the constant is refused explicitly.
        monkeypatch.setattr(config, "ADMIN_PASSWORD_MIN_LENGTH", 5)
        r = client.post("/api/admin/setup", headers=self.initial(), json={"new_password": "admin"})
        assert r.status_code == 400

    def test_setup_issues_one_admin_and_one_player_invitation_that_work_once(self, client, seeded):
        r = client.post("/api/admin/setup", headers=self.initial(), json={"new_password": ADMIN_PW})
        assert r.status_code == 200
        tokens = r.json()["invitations"]
        assert set(tokens) == {"admin", "player"}
        # the player token only signs a player up, the admin token only an admin
        assert client.post("/api/admin/signup", json={"name": "second", "password": ADMIN_PW,
                                                      "invitation": tokens["player"]}).status_code == 400
        assert client.post("/api/auth/signup", json={"name": "Bob", "password": PLAYER_PW,
                                                     "invitation": tokens["admin"]}).status_code == 400
        assert client.post("/api/auth/signup", json={"name": "Bob", "password": PLAYER_PW,
                                                     "invitation": tokens["player"]}).status_code == 201
        other = TestClient(app, **LOCAL)  # a fresh browser: Bob's session cookie would need his CSRF token
        assert other.post("/api/auth/signup", json={"name": "Cy", "password": PLAYER_PW,
                                                    "invitation": tokens["player"]}).status_code == 400  # single use
        assert other.post("/api/admin/signup", json={"name": "second", "password": ADMIN_PW,
                                                     "invitation": tokens["admin"]}).status_code == 201
        assert other.post("/api/admin/signup", json={"name": "third", "password": ADMIN_PW,
                                                     "invitation": tokens["admin"]}).status_code == 400

    def test_the_flag_clears_and_setup_cannot_run_twice(self, client, seeded):
        assert client.post("/api/admin/setup", headers=self.initial(), json={"new_password": ADMIN_PW}).status_code == 200
        assert seeded["store"].setup_open() is False
        assert client.get("/api/admin/state").json()["setup_open"] is False
        # the old credential is dead, the new one works as a normal admin
        assert client.get("/api/admin/whoami", headers=self.initial()).status_code == 401
        h = basic("admin", ADMIN_PW)
        assert client.get("/api/admin/whoami", headers=h).status_code == 200
        assert client.post("/api/admin/setup", headers=h, json={"new_password": ADMIN_PW + "x"}).status_code == 409

    def test_setup_is_audited_without_the_password(self, client, seeded):
        client.post("/api/admin/setup", headers=self.initial(), json={"new_password": ADMIN_PW})
        entries, _ = seeded["store"].list_audit(limit=10)
        assert "admin.setup_completed" in [e["action"] for e in entries]
        assert ADMIN_PW not in repr(entries) and "admin" != entries[0]["target"]

    def test_unusable_from_a_non_loopback_address(self, seeded):
        lan = TestClient(app, base_url="http://localhost", client=("192.168.1.9", 5))
        r = lan.post("/api/admin/setup", headers=self.initial(), json={"new_password": ADMIN_PW})
        assert r.status_code == 403 and seeded["store"].setup_open() is True

    def test_concurrent_completion_changes_the_password_once(self, seeded):
        store = seeded["store"]
        admin = store.get_by_name("admin")
        assert store.complete_setup(admin.player_uuid, FAST.hash(ADMIN_PW)) is True
        assert store.complete_setup(admin.player_uuid, FAST.hash("another-long-password-2")) is False
        assert FAST.verify(ADMIN_PW, store.get_by_name("admin").password_hash)


class TestSeeding:
    def test_seeded_once_on_an_empty_admin_table_and_not_reseeded(self, env):
        store = env["store"]
        first = store.seed_initial_admin(FAST.hash("admin"))
        assert first is not None and first.setup_required and first.role == "admin" and first.name == "admin"
        assert store.seed_initial_admin(FAST.hash("admin")) is None  # repeat start
        store._conn.execute("DELETE FROM accounts WHERE player_uuid = ?", (first.player_uuid,))
        assert store.seed_initial_admin(FAST.hash("admin")) is None  # not after removal either
        assert store.count_accounts("admin") == 0

    def test_not_seeded_when_an_admin_already_exists(self, env):
        make_admin(env)
        assert env["store"].seed_initial_admin(FAST.hash("admin")) is None

    def test_startup_seeds_warns_and_skips_online(self, env, monkeypatch, caplog):
        import importlib
        app_module = importlib.import_module("mtg_analyzer.api.app")
        monkeypatch.setattr(app_module, "get_account_store", lambda: env["store"])
        monkeypatch.setattr("mtg_analyzer.api.auth.get_password_hasher", lambda: FAST)
        monkeypatch.setattr(config, "RUN_MODE", "online")
        app_module._seed_initial_admin()
        assert env["store"].count_accounts("admin") == 0  # online: no seeding
        monkeypatch.setattr(config, "RUN_MODE", "localdev")
        with caplog.at_level("WARNING"):
            app_module._seed_initial_admin()
            app_module._seed_initial_admin()  # repeat start
        assert env["store"].count_accounts("admin") == 1
        assert any("ADMIN SETUP OPEN" in r.message for r in caplog.records)
        assert "admin'" in caplog.text and "password" in caplog.text and "admin'  " not in caplog.text

    def test_reserved_name_cannot_be_registered_by_a_player(self, client, env):
        token = env["store"].create_invitation(acc.OPERATOR_CREATOR, acc.ROLE_PLAYER, enforce_limits=False)
        r = client.post("/api/auth/signup", json={"name": "admin", "password": PLAYER_PW, "invitation": token})
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# Admin invitations
# ---------------------------------------------------------------------------

class TestInvitations:
    def test_admin_mints_both_roles_and_the_token_is_never_listed(self, client, env):
        h = admin_headers(env)
        a = client.post("/api/admin/invitations", headers=h, json={"role": "admin"})
        p = client.post("/api/admin/invitations", headers=h, json={"role": "player"})
        assert a.status_code == p.status_code == 201
        listing = client.get("/api/admin/invitations", headers=h).json()
        assert {i["role"] for i in listing} == {"admin", "player"}
        assert a.json()["token"] not in repr(listing) and p.json()["token"] not in repr(listing)
        assert all(len(i["id"]) == acc.INVITATION_ID_LENGTH for i in listing)

    def test_unknown_role_is_rejected(self, client, env):
        assert client.post("/api/admin/invitations", headers=admin_headers(env), json={"role": "root"}).status_code == 422

    def test_players_and_anonymous_cannot_mint_admin_tokens(self, client, env):
        make_player(env)
        player = player_login(env)
        assert player.post("/api/auth/invitations").status_code == 201  # a player token, never admin
        tokens = [i for i in env["store"].list_invitations() if i["role"] == "admin"]
        assert tokens == []
        assert player.post("/api/admin/invitations", json={"role": "admin"}).status_code == 401
        assert client.post("/api/admin/invitations", json={"role": "admin"}).status_code == 401
        assert client.post("/api/admin/invitations", headers=basic("Alice", PLAYER_PW), json={"role": "admin"}).status_code == 401

    def test_admin_signup_enforces_the_15_character_policy(self, client, env):
        token = env["store"].create_invitation(acc.OPERATOR_CREATOR, acc.ROLE_ADMIN, enforce_limits=False)
        short = "a1b2c3d4e5f6g7"
        r = client.post("/api/admin/signup", json={"name": "newadmin", "password": short, "invitation": token})
        assert r.status_code == 400 and r.json()["detail"]["code"] == "password_too_short"
        r = client.post("/api/admin/signup", json={"name": "newadmin", "password": short + "h", "invitation": token})
        assert r.status_code == 201 and "set-cookie" not in r.headers
        created = env["store"].get_by_name("newadmin")
        assert created.role == "admin" and not created.setup_required
        assert client.get("/api/admin/whoami", headers=basic("newadmin", short + "h")).status_code == 200

    def test_admin_signup_rejects_a_role_field_a_colon_and_reserved_names(self, client, env):
        token = env["store"].create_invitation(acc.OPERATOR_CREATOR, acc.ROLE_ADMIN, enforce_limits=False)
        base = {"password": ADMIN_PW, "invitation": token}
        assert client.post("/api/admin/signup", json={"name": "x1y", "role": "player", **base}).status_code == 422
        assert client.post("/api/admin/signup", json={"name": "a:b", **base}).status_code == 400
        assert client.post("/api/admin/signup", json={"name": "root", **base}).status_code == 400
        assert env["store"].count_accounts("admin") == 0

    def test_revoking_an_invitation(self, client, env):
        h = admin_headers(env)
        token = client.post("/api/admin/invitations", headers=h, json={"role": "admin"}).json()["token"]
        inv_id = client.get("/api/admin/invitations", headers=h).json()[0]["id"]
        assert client.delete(f"/api/admin/invitations/{inv_id}", headers=h).status_code == 204
        r = client.post("/api/admin/signup", json={"name": "late", "password": ADMIN_PW, "invitation": token})
        assert r.status_code == 400
        assert client.delete("/api/admin/invitations/zzzz", headers=h).status_code == 404

    def test_a_disabled_creator_invalidates_its_tokens(self, client, env):
        boss = make_admin(env, "boss")
        token = env["store"].create_invitation(boss.player_uuid, acc.ROLE_ADMIN, enforce_limits=False)
        env["store"].set_disabled(boss.player_uuid, True)
        r = client.post("/api/admin/signup", json={"name": "late", "password": ADMIN_PW, "invitation": token})
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# Players
# ---------------------------------------------------------------------------

class TestPlayers:
    def test_list_search_and_pagination_exclude_admins(self, client, env):
        h = admin_headers(env)
        for name in ("Alice", "Albert", "Bob"):
            make_player(env, name)
        r = client.get("/api/admin/players", headers=h).json()
        assert r["total"] == 3 and {p["name"] for p in r["players"]} == {"Alice", "Albert", "Bob"}
        assert "password_hash" not in repr(r)
        found = client.get("/api/admin/players?q=AL", headers=h).json()
        assert {p["name"] for p in found["players"]} == {"Alice", "Albert"}
        assert len(client.get("/api/admin/players?limit=1", headers=h).json()["players"]) == 1

    def test_create_a_player_goes_through_an_invitation(self, client, env):
        token = client.post("/api/admin/invitations", headers=admin_headers(env), json={"role": "player"}).json()["token"]
        assert client.post("/api/auth/signup", json={"name": "Newbie", "password": PLAYER_PW, "invitation": token}).status_code == 201

    def test_disable_blocks_login_and_kills_existing_sessions_enable_restores(self, client, env):
        h = admin_headers(env)
        alice = make_player(env)
        player = player_login(env)
        assert player.get("/api/auth/me").json()["authenticated"] is True
        assert client.post(f"/api/admin/players/{alice.player_uuid}/disable", headers=h).status_code == 204
        assert player.get("/api/auth/me").json() == {"authenticated": False}
        assert player.post("/api/decks/save", json={"name": "x"}).status_code == 401  # PLR-18: reads are public
        assert client.post("/api/auth/login", json={"name": "Alice", "password": PLAYER_PW}).status_code == 401
        listed = client.get("/api/admin/players", headers=h).json()["players"][0]
        assert listed["disabled"] is True
        assert client.post(f"/api/admin/players/{alice.player_uuid}/enable", headers=h).status_code == 204
        assert client.post("/api/auth/login", json={"name": "Alice", "password": PLAYER_PW}).status_code == 200

    def test_revoke_sessions_keeps_the_account_usable(self, client, env):
        h = admin_headers(env)
        alice = make_player(env)
        player = player_login(env)
        assert client.post(f"/api/admin/players/{alice.player_uuid}/revoke-sessions", headers=h).status_code == 204
        assert player.get("/api/auth/me").json() == {"authenticated": False}
        assert client.post("/api/auth/login", json={"name": "Alice", "password": PLAYER_PW}).status_code == 200

    def test_admin_targets_look_like_unknown_ids(self, client, env):
        h = admin_headers(env)
        other = make_admin(env, "second")
        for action in ("disable", "enable", "revoke-sessions"):
            assert client.post(f"/api/admin/players/{other.player_uuid}/{action}", headers=h).status_code == 404
        assert client.get(f"/api/admin/players/{other.player_uuid}/delete-preview", headers=h).status_code == 404
        r = client.post(f"/api/admin/players/{other.player_uuid}/delete", headers=h, json={"confirm_name": "second"})
        assert r.status_code == 404 and env["store"].get("second") is None and env["store"].get_by_name("second")
        assert client.post("/api/admin/players/unknown/disable", headers=h).status_code == 404

    def test_the_default_localuser_cannot_be_deleted_or_disabled(self, client, env):
        h = admin_headers(env)
        local = env["store"].ensure_default_local()
        assert client.post(f"/api/admin/players/{local.player_uuid}/disable", headers=h).status_code == 409
        r = client.post(f"/api/admin/players/{local.player_uuid}/delete", headers=h, json={"confirm_name": "local"})
        assert r.status_code == 409 and env["store"].get_by_name("local") is not None
        assert client.get(f"/api/admin/players/{local.player_uuid}/delete-preview", headers=h).json()["deletable"] is False

    def _populate(self, env, alice):
        for i in range(2):
            env["decks"].save_private(Deck(name=f"secret {i}", mainboard_text="1 Island"), alice.player_uuid)
        env["assets"].save_token_image(alice.player_uuid, "Goblin", "image/png", b"\x89PNG0")
        env["assets"].add_favorite_deck(alice.player_uuid, "deck-1")

    def test_delete_preview_shows_counts_only(self, client, env):
        h = admin_headers(env)
        alice = make_player(env)
        self._populate(env, alice)
        player_login(env)
        preview = client.get(f"/api/admin/players/{alice.player_uuid}/delete-preview", headers=h).json()
        assert preview["decks"] == 2 and preview["assets"] == 2 and preview["sessions"] == 1
        assert "secret" not in repr(preview) and preview["tombstone_days"] == config.NAME_TOMBSTONE_SECONDS / 86400

    def test_delete_needs_the_exact_name_then_cascades(self, client, env):
        h = admin_headers(env)
        alice = make_player(env)
        bob = make_player(env, "Bobby")
        self._populate(env, alice)
        env["decks"].save_private(Deck(name="bobs"), bob.player_uuid)
        session = env["sessions"].create_goldfish([], owner=alice.player_uuid) if False else None
        player = player_login(env)
        url = f"/api/admin/players/{alice.player_uuid}/delete"
        assert client.post(url, headers=h, json={"confirm_name": "alice"}).status_code == 400  # exact match
        assert env["store"].get(alice.player_uuid) is not None
        r = client.post(url, headers=h, json={"confirm_name": "Alice"})
        assert r.status_code == 200 and r.json()["decks"] == 2
        assert env["store"].get(alice.player_uuid) is None
        assert env["decks"].count_private(alice.player_uuid) == 0
        assert sum(env["assets"].count_for_owner(alice.player_uuid).values()) == 0
        assert env["store"].list_sessions(alice.player_uuid) == []
        assert player.get("/api/auth/me").json() == {"authenticated": False}
        assert env["decks"].count_private(bob.player_uuid) == 1  # others untouched
        assert env["store"].drain_deleted() == [alice.player_uuid]

    def test_delete_removes_the_players_non_table_game_sessions(self, client, env):
        alice = make_player(env)
        mgr = env["sessions"]
        keep = mgr.create_replay({"players": [{"name": "a"}, {"name": "b"}]}, loader=None, owner="someone-else") if False else None
        from mtg_analyzer.services import admin_service
        class Fake: owner = alice.player_uuid; id = "s1"
        mgr._sessions["s1"] = Fake()
        mgr._last_access["s1"] = 0.0
        other = Fake(); other.owner = "other"; other.id = "s2"
        mgr._sessions["s2"] = other
        mgr._last_access["s2"] = 0.0
        admin_service.delete_player(env["store"], env["decks"], env["assets"], mgr, alice)
        assert "s1" not in mgr._sessions and "s2" in mgr._sessions

    def test_the_name_is_tombstoned_for_the_retention_period(self, client, env, monkeypatch):
        h = admin_headers(env)
        alice = make_player(env)
        client.post(f"/api/admin/players/{alice.player_uuid}/delete", headers=h, json={"confirm_name": "Alice"})
        token = env["store"].create_invitation(acc.OPERATOR_CREATOR, acc.ROLE_PLAYER, enforce_limits=False)
        r = client.post("/api/auth/signup", json={"name": "alice", "password": PLAYER_PW, "invitation": token})
        assert r.status_code == 409 and r.json()["detail"]["code"] == "name_taken"
        env["store"]._now = lambda: time.time() + config.NAME_TOMBSTONE_SECONDS + 5  # the retention lapsed
        token = env["store"].create_invitation(acc.OPERATOR_CREATOR, acc.ROLE_PLAYER, enforce_limits=False)
        again = client.post("/api/auth/signup", json={"name": "alice", "password": PLAYER_PW, "invitation": token})
        assert again.status_code == 201
        assert again.json()["player_uuid"] != alice.player_uuid  # the uuid is never reused

    def test_tombstone_days_are_configurable(self):
        assert config.NAME_TOMBSTONE_SECONDS == 7 * 24 * 3600  # default; MTG_NAME_TOMBSTONE_DAYS overrides

    def test_there_is_no_admin_initiated_password_reset(self, client):
        paths = {r.path for r in api_routes()}
        assert not [p for p in paths if "/api/admin" in p and ("reset" in p or "password" in p and "change" not in p)]
        assert not [p for p in paths if "/api/admin/players" in p and "password" in p]

    def test_admin_cannot_read_private_decks_or_assets(self, client, env):
        h = admin_headers(env)
        alice = make_player(env)
        env["decks"].save_private(Deck(name="TOPSECRET"), alice.player_uuid)
        deck_id = env["decks"].list_decks(alice.player_uuid)[0].id
        assert client.get(f"/api/admin/decks/{deck_id}", headers=h).status_code == 404
        assert "TOPSECRET" not in client.get("/api/admin/decks", headers=h).text
        assert client.get(f"/api/decks/{deck_id}", headers=h).status_code == 404  # an admin is anonymous here (PLR-18)
        assert client.put(f"/api/admin/decks/{deck_id}", headers=h, json={"name": "x"}).status_code == 404
        assert client.post(f"/api/admin/decks/{deck_id}/delete", headers=h, json={"confirm_name": "TOPSECRET"}).status_code == 404
        assert env["decks"].count_private(alice.player_uuid) == 1


# ---------------------------------------------------------------------------
# Global decks
# ---------------------------------------------------------------------------

class TestGlobalDecks:
    def test_crud_and_players_see_the_global_deck(self, client, env):
        h = admin_headers(env)
        make_player(env)
        created = client.post("/api/admin/decks", headers=h, json={
            "name": "Starter", "commanderText": "1 Atraxa", "mainboardText": "1 Island", "author": "Boss",
        }).json()
        deck_id = created["id"]
        assert [d["name"] for d in client.get("/api/admin/decks", headers=h).json()] == ["Starter"]
        assert client.get(f"/api/admin/decks/{deck_id}", headers=h).json()["mainboardText"] == "1 Island"
        player = player_login(env)
        visible = player.get("/api/decks").json()
        assert [d["name"] for d in visible] == ["Starter"] and visible[0]["scope"] == "global"
        assert player.post("/api/decks/save", json={"id": deck_id, "name": "mine"}).status_code == 403
        assert player.delete(f"/api/decks/{deck_id}").status_code == 403
        copy = player.post(f"/api/decks/{deck_id}/copy").json()
        assert copy["id"] != deck_id and copy["scope"] == "private"
        updated = client.put(f"/api/admin/decks/{deck_id}", headers=h, json={
            "name": "Starter v2", "commanderText": "1 Atraxa", "mainboardText": "1 Island\n1 Swamp"}).json()
        assert updated["name"] == "Starter v2" and updated["id"] == deck_id
        assert env["decks"].get_global(deck_id).scope == "global"
        assert player.get(f"/api/decks/{copy['id']}").json()["name"] == "Starter"  # copy unchanged

    def test_edit_resets_the_derived_caches(self, client, env):
        h = admin_headers(env)
        deck = Deck(name="d", mainboard_text="1 Island", color_identity=["G"], commanders=["x"])
        env["decks"].save_global(deck)
        client.put(f"/api/admin/decks/{deck.id}", headers=h, json={"name": "d", "mainboardText": "1 Swamp"})
        stored = env["decks"].get_global(deck.id)
        assert stored.color_identity is None and stored.commanders is None

    def test_delete_has_preview_and_simple_confirmation(self, client, env):
        # VIS-22: the page asks one "sind Sie sicher" question; the server needs no typed name.
        h = admin_headers(env)
        deck = Deck(name="Doomed", mainboard_text="1 Island\n\n1 Swamp")
        env["decks"].save_global(deck)
        assert client.get(f"/api/admin/decks/{deck.id}/delete-preview", headers=h).json() == {
            "name": "Doomed", "lines": 2, "author": None, "created_at": deck.created_at}
        assert client.post(f"/api/admin/decks/{deck.id}/delete", headers=h).status_code == 200
        assert env["decks"].get_global(deck.id) is None
        assert client.get(f"/api/admin/decks/{deck.id}", headers=h).status_code == 404

    def test_oversized_decks_are_refused(self, client, env):
        r = client.post("/api/admin/decks", headers=admin_headers(env),
                        json={"name": "big", "mainboardText": "x" * (config.ADMIN_DECK_TEXT_MAX + 1)})
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

def _wait_done(client, job_id, headers):
    for _ in range(100):
        view = client.get(f"/api/admin/jobs/{job_id}", headers=headers).json()
        if view["state"] != "running":
            return view
        time.sleep(0.02)
    raise AssertionError("job did not finish")


class TestJobs:
    def test_start_progress_and_result(self, client, env):
        h = admin_headers(env)
        r = client.post("/api/admin/jobs", headers=h, json={"kind": "card-pool"})
        assert r.status_code == 202
        job_id, token = r.json()["job"]["id"], r.json()["poll_token"]
        view = _wait_done(client, job_id, h)
        assert view["state"] == "succeeded" and view["progress"] == ["lade"] and view["result"] == {"updated": True}
        assert [j["id"] for j in client.get("/api/admin/jobs", headers=h).json()["jobs"]] == [job_id]
        assert token not in client.get("/api/admin/jobs", headers=h).text

    def test_poll_token_works_without_a_password_and_only_for_its_job(self, client, env):
        h = admin_headers(env)
        a = client.post("/api/admin/jobs", headers=h, json={"kind": "card-pool"}).json()
        b = client.post("/api/admin/jobs", headers=h, json={"kind": "combos"}).json()
        _wait_done(client, a["job"]["id"], h)
        ok = client.get(f"/api/admin/jobs/{a['job']['id']}", headers={"X-Job-Token": a["poll_token"]})
        assert ok.status_code == 200 and ok.json()["kind"] == "card-pool"
        cross = client.get(f"/api/admin/jobs/{b['job']['id']}", headers={"X-Job-Token": a["poll_token"]})
        assert cross.status_code == 404
        assert client.get(f"/api/admin/jobs/{a['job']['id']}", headers={"X-Job-Token": "guess"}).status_code == 404
        assert client.get(f"/api/admin/jobs/{a['job']['id']}").status_code == 401
        # the token reads nothing else: no list, no other admin route
        assert client.get("/api/admin/jobs", headers={"X-Job-Token": a["poll_token"]}).status_code == 401
        assert client.get("/api/admin/players", headers={"X-Job-Token": a["poll_token"]}).status_code == 401

    def test_poll_token_stays_loopback_only(self, client, env):
        h = admin_headers(env)
        job = client.post("/api/admin/jobs", headers=h, json={"kind": "card-pool"}).json()
        lan = TestClient(app, base_url="http://localhost", client=("192.168.1.9", 5))
        assert lan.get(f"/api/admin/jobs/{job['job']['id']}", headers={"X-Job-Token": job["poll_token"]}).status_code == 403

    def test_allowlist_only(self, client, env):
        h = admin_headers(env)
        for kind in ("shell", "../scripts/x", "", "card_pool"):
            assert client.post("/api/admin/jobs", headers=h, json={"kind": kind}).status_code == 422
        assert client.post("/api/admin/jobs", headers=h, json={"kind": "card-pool", "cmd": "rm"}).status_code == 422

    def test_one_running_job_per_kind(self, client, env):
        import threading
        gate = threading.Event()
        env["jobs"]._runners["combos"] = lambda report: (gate.wait(5), {})[1]
        h = admin_headers(env)
        first = client.post("/api/admin/jobs", headers=h, json={"kind": "combos"})
        assert first.status_code == 202
        assert client.post("/api/admin/jobs", headers=h, json={"kind": "combos"}).status_code == 409
        gate.set()
        assert _wait_done(client, first.json()["job"]["id"], h)["state"] == "succeeded"

    def test_failure_reports_only_the_exception_type(self, client, env):
        def boom(report):
            raise OSError("/secret/path leaked")
        env["jobs"]._runners["combos"] = boom
        h = admin_headers(env)
        job = client.post("/api/admin/jobs", headers=h, json={"kind": "combos"}).json()["job"]
        view = _wait_done(client, job["id"], h)
        assert view["state"] == "failed" and view["error"] == "OSError" and "secret" not in repr(view)

    def test_progress_is_bounded(self, env):
        jobs = AdminJobs(runners={"card-pool": lambda report: [report(f"line {i}") for i in range(500)] and {}})
        job, _ = jobs.start("card-pool", "boss", synchronous=True)
        assert len(jobs.get(job.id)["progress"]) == config.ADMIN_JOB_LOG_LINES

    def test_job_start_and_finish_are_audited(self, client, env):
        h = admin_headers(env)
        job = client.post("/api/admin/jobs", headers=h, json={"kind": "card-pool"}).json()["job"]
        _wait_done(client, job["id"], h)
        time.sleep(0.05)
        actions = [e["action"] for e in env["store"].list_audit(limit=10)[0]]
        assert "job.started" in actions and "job.finished" in actions

    def test_job_view_never_contains_the_token(self, client, env):
        h = admin_headers(env)
        r = client.post("/api/admin/jobs", headers=h, json={"kind": "card-pool"}).json()
        assert r["poll_token"] not in repr(r["job"])


# ---------------------------------------------------------------------------
# PLR-17: direct calls to the update routes
# ---------------------------------------------------------------------------

class TestUpdateRoutesEnforcement:
    @pytest.fixture(autouse=True)
    def _stub_updates(self, monkeypatch):
        from types import SimpleNamespace

        from mtg_analyzer.api.dependencies import get_card_database, get_commander_spellbook_database
        calls = []
        monkeypatch.setattr("mtg_analyzer.api.cards.subprocess.run",
                            lambda *a, **k: (calls.append("pool"), SimpleNamespace(returncode=0, stdout="ok", stderr=""))[1])
        fake_spellbook = SimpleNamespace(update=lambda: (calls.append("combos"), {"variantCount": 0})[1])
        app.dependency_overrides[get_commander_spellbook_database] = lambda: fake_spellbook
        app.dependency_overrides[get_card_database] = lambda: SimpleNamespace(count=lambda: 1)
        self.calls = calls
        yield
        app.dependency_overrides.pop(get_commander_spellbook_database, None)
        app.dependency_overrides.pop(get_card_database, None)

    UPDATE_ROUTES = ("/api/cards/update", "/api/combos/update")

    def test_anonymous_is_denied(self, client):
        for path in self.UPDATE_ROUTES:
            assert client.post(path).status_code == 401
        assert self.calls == []

    def test_a_signed_in_player_is_denied_by_direct_call(self, env):
        make_player(env)
        player = player_login(env)
        for path in self.UPDATE_ROUTES:
            assert player.post(path).status_code == 401
            assert player.post(path, headers=basic("Alice", PLAYER_PW)).status_code == 401
        assert self.calls == []

    def test_a_lan_client_is_denied_even_with_admin_credentials(self, env):
        headers = admin_headers(env)
        lan = TestClient(app, base_url="http://localhost", client=("192.168.1.9", 5))
        for path in self.UPDATE_ROUTES:
            assert lan.post(path, headers=headers).status_code == 403
        assert self.calls == []

    def test_an_admin_can_update(self, client, env):
        headers = admin_headers(env)
        assert client.post("/api/cards/update", headers=headers).status_code == 200
        assert client.post("/api/combos/update", headers=headers).status_code == 200
        assert self.calls == ["pool", "combos"]

    def test_route_inventory_every_update_route_is_admin_only_and_no_llm_route_exists(self):
        """A new `*/update` route (or an `llm` route) must be added to the admin gate on purpose."""
        from mtg_analyzer.api.admin_auth import require_admin

        def deps(route):
            return {d.call for d in route.dependant.dependencies} | {
                sub.call for d in route.dependant.dependencies for sub in d.dependencies}

        update_routes = [r for r in api_routes() if "update" in r.path.lower()]
        assert {r.path for r in update_routes} == set(self.UPDATE_ROUTES)
        for route in update_routes:
            assert require_admin in deps(route), route.path
        assert [r.path for r in api_routes() if "llm" in r.path.lower()] == []
