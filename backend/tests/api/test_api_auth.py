"""PLR-9a: /api/auth — invitation signup, login, sessions, CSRF, throttling, invitations."""

import pytest
from fastapi.testclient import TestClient

from mtg_analyzer import config
from mtg_analyzer.api.app import app
from mtg_analyzer.api.auth import get_login_limiter, get_password_hasher, get_signup_limiter
from mtg_analyzer.api.dependencies import get_account_store
from mtg_analyzer.services.account_store import AccountStore
from mtg_analyzer.services.password_hasher import PasswordHasher
from mtg_analyzer.services.rate_limiter import FailureLimiter

PW = "correct horse 9!"
FAST = PasswordHasher(n=2 ** 4)


@pytest.fixture
def store(tmp_path):
    s = AccountStore(tmp_path / "accounts.db")
    app.dependency_overrides[get_account_store] = lambda: s
    app.dependency_overrides[get_password_hasher] = lambda: FAST
    login = FailureLimiter(3, 60.0)
    signup = FailureLimiter(50, 60.0)
    app.dependency_overrides[get_login_limiter] = lambda: login
    app.dependency_overrides[get_signup_limiter] = lambda: signup
    yield s
    for dep in (get_account_store, get_password_hasher, get_login_limiter, get_signup_limiter):
        app.dependency_overrides.pop(dep, None)


@pytest.fixture
def client(store):
    return TestClient(app)


def _invite(store, role="player"):
    admin = store.get_by_name("seed-admin") or store.create_account_unchecked("seed-admin", FAST.hash("x"), "admin")
    return store.create_invitation(admin.player_uuid, role, enforce_limits=False)


def _signup(client, store, name="Alice", password=PW):
    return client.post("/api/auth/signup", json={"name": name, "password": password, "invitation": _invite(store)})


def _csrf(resp):
    return {"X-CSRF-Token": resp.json()["csrf_token"]}


def test_anonymous_me(client):
    r = client.get("/api/auth/me")
    assert r.json() == {"authenticated": False}
    assert r.headers["cache-control"] == "no-store"


def test_signup_login_me_logout(client, store):
    r = _signup(client, store)
    assert r.status_code == 201
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "mtg_session" in cookie
    assert client.get("/api/auth/me").json()["name"] == "Alice"
    assert client.post("/api/auth/logout", headers=_csrf(r)).status_code == 204
    assert client.get("/api/auth/me").json() == {"authenticated": False}
    r2 = client.post("/api/auth/login", json={"name": "alice", "password": PW})
    assert r2.status_code == 200 and r2.json()["name"] == "Alice"


def test_signup_needs_a_valid_invitation_and_never_a_role(client, store):
    body = {"name": "Mallory", "password": PW}
    assert client.post("/api/auth/signup", json={**body, "invitation": "nope"}).status_code == 400
    assert client.post("/api/auth/signup", json={**body}).status_code == 422
    assert client.post("/api/auth/signup", json={**body, "invitation": "x", "role": "admin"}).status_code == 422
    admin_token = _invite(store, "admin")
    r = client.post("/api/auth/signup", json={**body, "invitation": admin_token})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "invalid_invitation"
    assert store.count_accounts("player") == 0


def test_invitation_is_single_use(client, store):
    token = _invite(store)
    ok = client.post("/api/auth/signup", json={"name": "Alice", "password": PW, "invitation": token})
    again = client.post("/api/auth/signup", json={"name": "Bob", "password": PW, "invitation": token})
    assert ok.status_code == 201 and again.status_code == 400


@pytest.mark.parametrize("pw,code", [("short", "password_too_short"), ("password123", "password_blocklisted")])
def test_signup_password_policy(client, store, pw, code):
    r = _signup(client, store, password=pw)
    assert r.status_code == 400 and r.json()["detail"]["code"] == code


def test_name_taken_and_invalid_name(client, store):
    _signup(client, store, "Alice")
    assert _signup(client, store, "ALICE").status_code == 409
    assert _signup(client, store, "admin").status_code == 400


def test_login_failures_are_generic_and_throttled(client, store):
    _signup(client, store, "Alice")
    admin = store.get_by_name("seed-admin")
    store.set_password(admin.player_uuid, FAST.hash(PW))
    wrong = client.post("/api/auth/login", json={"name": "Alice", "password": "wrong-password-1"})
    unknown = client.post("/api/auth/login", json={"name": "Nobody", "password": PW})
    as_admin = client.post("/api/auth/login", json={"name": "seed-admin", "password": PW})
    assert wrong.status_code == unknown.status_code == as_admin.status_code == 401
    assert wrong.json() == unknown.json() == as_admin.json()
    # budget of 3 failures per source: the 4th attempt is throttled even with the right password
    r = client.post("/api/auth/login", json={"name": "Alice", "password": PW})
    assert r.status_code == 429 and "retry-after" in r.headers


def test_disabled_account_cannot_log_in_and_sessions_die(client, store):
    r = _signup(client, store, "Alice")
    alice = store.get_by_name("Alice")
    store.set_disabled(alice.player_uuid, True)
    assert client.get("/api/auth/me").json() == {"authenticated": False}
    assert client.post("/api/auth/login", json={"name": "Alice", "password": PW}).status_code == 401


def test_default_localuser_cannot_log_in_here(client, store):
    store.create_account_unchecked("local", FAST.hash(PW), "player", is_default_local=True)
    assert client.post("/api/auth/login", json={"name": "local", "password": PW}).status_code == 401


def test_csrf_token_required_for_cookie_bearing_mutations(client, store):
    r = _signup(client, store)
    assert client.post("/api/auth/logout").status_code == 403
    assert client.post("/api/auth/logout", headers={"X-CSRF-Token": "wrong"}).status_code == 403
    assert client.post("/api/auth/logout", headers=_csrf(r)).status_code == 204


def test_password_change_revokes_other_sessions(client, store):
    r = _signup(client, store, "Alice")
    other = TestClient(app)
    other.post("/api/auth/login", json={"name": "Alice", "password": PW})
    assert other.get("/api/auth/me").json()["authenticated"]
    bad = client.post("/api/auth/password-change", headers=_csrf(r),
                      json={"current_password": "nope-nope-nope", "new_password": "another pass 7?"})
    assert bad.status_code == 401
    weak = client.post("/api/auth/password-change", headers=_csrf(r),
                       json={"current_password": PW, "new_password": "short"})
    assert weak.status_code == 400
    ok = client.post("/api/auth/password-change", headers=_csrf(r),
                     json={"current_password": PW, "new_password": "another pass 7?"})
    assert ok.status_code == 204
    assert client.get("/api/auth/me").json()["authenticated"]
    assert not other.get("/api/auth/me").json()["authenticated"]
    assert TestClient(app).post("/api/auth/login", json={"name": "Alice", "password": "another pass 7?"}).status_code == 200


def test_logout_all(client, store):
    r = _signup(client, store, "Alice")
    other = TestClient(app)
    other.post("/api/auth/login", json={"name": "Alice", "password": PW})
    assert client.post("/api/auth/logout-all", headers=_csrf(r)).status_code == 204
    assert not other.get("/api/auth/me").json()["authenticated"]


def test_player_invitations_create_list_revoke_and_limits(client, store, monkeypatch):
    monkeypatch.setattr(config, "INVITE_MAX_OUTSTANDING_PER_PLAYER", 2)
    r = _signup(client, store, "Alice")
    h = _csrf(r)
    assert client.post("/api/auth/invitations").status_code == 403  # CSRF
    made = client.post("/api/auth/invitations", headers=h)
    assert made.status_code == 201
    token = made.json()["token"]
    listing = client.get("/api/auth/invitations").json()
    assert len(listing) == 1 and token not in str(listing) and listing[0]["role"] == "player"
    client.post("/api/auth/invitations", headers=h)
    assert client.post("/api/auth/invitations", headers=h).status_code == 429
    assert client.delete(f"/api/auth/invitations/{listing[0]['id']}", headers=h).status_code == 204
    assert client.delete("/api/auth/invitations/deadbeefdeadbeef", headers=h).status_code == 404
    revoked = TestClient(app).post("/api/auth/signup", json={"name": "Bob", "password": PW, "invitation": token})
    assert revoked.status_code == 400
    # invitations need a login
    assert TestClient(app).post("/api/auth/invitations").status_code == 401


def test_cannot_revoke_someone_elses_invitation(client, store):
    r = _signup(client, store, "Alice")
    mine = client.post("/api/auth/invitations", headers=_csrf(r))
    assert mine.status_code == 201
    other = TestClient(app)
    invite = _invite(store)
    r2 = other.post("/api/auth/signup", json={"name": "Bob", "password": PW, "invitation": invite})
    listing = client.get("/api/auth/invitations").json()
    assert other.delete(f"/api/auth/invitations/{listing[0]['id']}", headers=_csrf(r2)).status_code == 404


def test_policy_endpoint(client):
    body = client.get("/api/auth/policy").json()
    assert body["min_length"] == config.PASSWORD_MIN_LENGTH
