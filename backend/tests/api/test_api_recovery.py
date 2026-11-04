"""PLR-9d: OS-operator password recovery (plan section 6: no admin-initiated reset)."""

import importlib.util
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mtg_analyzer import config
from mtg_analyzer.api.admin_auth import get_admin_limiter
from mtg_analyzer.api.app import app
from mtg_analyzer.api.auth import get_login_limiter, get_password_hasher
from mtg_analyzer.api.dependencies import get_account_store
from mtg_analyzer.services import account_store as acc
from mtg_analyzer.services.account_store import AccountStore
from mtg_analyzer.services.password_hasher import PasswordHasher
from mtg_analyzer.services.rate_limiter import FailureLimiter
from tests.support.auth import use_test_key

pytestmark = pytest.mark.real_auth

FAST = PasswordHasher(n=2 ** 4)
LOCAL = dict(base_url="http://localhost", client=("127.0.0.1", 50000))
SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "manage_accounts.py"


def load_script():
    spec = importlib.util.spec_from_file_location("manage_accounts_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def store(tmp_path, monkeypatch):
    s = AccountStore(tmp_path / "accounts.db", key=use_test_key(monkeypatch))
    monkeypatch.setattr(config, "ACCOUNTS_DB_PATH", tmp_path / "accounts.db")
    overrides = {
        get_account_store: lambda: s, get_password_hasher: lambda: FAST,
        get_login_limiter: lambda: FailureLimiter(5, 60.0), get_admin_limiter: lambda: FailureLimiter(5, 60.0),
    }
    app.dependency_overrides.update(overrides)
    yield s
    for dep in overrides:
        app.dependency_overrides.pop(dep, None)
    s.close()


def issue(capsys, name):
    assert load_script().main(["recover", name]) == 0
    out = capsys.readouterr().out
    return next(line.strip() for line in out.splitlines() if line.startswith("  ")).strip()


def test_operator_command_issues_a_credential_and_audits_it(store, capsys):
    alice = store.create_account_unchecked("Alice", FAST.hash("old password 1!"), acc.ROLE_PLAYER)
    credential = issue(capsys, "Alice")
    assert len(credential) >= 40 and credential not in repr(store.list_audit(limit=5))
    entry = store.list_audit(limit=1)[0][0]
    assert (entry["actor"], entry["action"], entry["target"]) == ("operator", "recovery.issued", "player:Alice")
    assert alice.player_uuid


def test_command_refuses_unknown_accounts_and_the_default_localuser(store, capsys):
    store.ensure_default_local()
    assert load_script().main(["recover", "nobody"]) == 1
    assert load_script().main(["recover", "local"]) == 1


def test_player_redeems_once_sessions_end_and_nobody_is_signed_in(store, capsys):
    store.create_account_unchecked("Alice", FAST.hash("old password 1!"), acc.ROLE_PLAYER)
    client = TestClient(app, **LOCAL)
    login = client.post("/api/auth/login", json={"name": "Alice", "password": "old password 1!"})
    assert login.status_code == 200
    credential = issue(capsys, "Alice")
    fresh = TestClient(app, **LOCAL)
    body = {"name": "Alice", "recovery_token": credential, "new_password": "brand new pass 2!"}
    r = fresh.post("/api/auth/recover", json=body)
    assert r.status_code == 204 and "set-cookie" not in r.headers  # never auto-login
    assert client.get("/api/auth/me").json() == {"authenticated": False}  # old sessions revoked
    assert fresh.post("/api/auth/login", json={"name": "Alice", "password": "old password 1!"}).status_code == 401
    assert fresh.post("/api/auth/login", json={"name": "Alice", "password": "brand new pass 2!"}).status_code == 200
    assert TestClient(app, **LOCAL).post("/api/auth/recover", json=body).status_code == 400  # single use


def test_player_policy_and_wrong_credential(store, capsys):
    store.create_account_unchecked("Alice", FAST.hash("old password 1!"), acc.ROLE_PLAYER)
    credential = issue(capsys, "Alice")
    client = TestClient(app, **LOCAL)
    weak = client.post("/api/auth/recover", json={"name": "Alice", "recovery_token": credential, "new_password": "short"})
    assert weak.status_code == 400 and weak.json()["detail"]["code"] == "password_too_short"
    # a rejected password does not burn the credential
    ok = client.post("/api/auth/recover", json={"name": "Alice", "recovery_token": credential, "new_password": "good new pass 3!"})
    assert ok.status_code == 204
    bad = client.post("/api/auth/recover", json={"name": "Alice", "recovery_token": "nope", "new_password": "good new pass 3!"})
    assert bad.status_code == 400 and bad.json()["detail"]["code"] == "invalid_recovery"


def test_admin_credentials_recover_only_through_the_admin_route_with_the_15_character_policy(store, capsys):
    store.create_account_unchecked("boss", FAST.hash("a-long-admin-passphrase-1"), acc.ROLE_ADMIN)
    credential = issue(capsys, "boss")
    client = TestClient(app, **LOCAL)
    as_player = client.post("/api/auth/recover", json={"name": "boss", "recovery_token": credential, "new_password": "good new pass 3!"})
    assert as_player.status_code == 400  # the player route never touches an admin
    short = client.post("/api/admin/recover", json={"name": "boss", "recovery_token": credential, "new_password": "a1b2c3d4e5f6g7"})
    assert short.status_code == 400 and short.json()["detail"]["code"] == "password_too_short"
    ok = client.post("/api/admin/recover", json={"name": "boss", "recovery_token": credential, "new_password": "fifteen-chars-ok"})
    assert ok.status_code == 204 and "set-cookie" not in ok.headers
    assert TestClient(app, **LOCAL).post("/api/admin/recover", json={
        "name": "boss", "recovery_token": credential, "new_password": "fifteen-chars-ok2"}).status_code == 400
    import base64
    h = {"Authorization": "Basic " + base64.b64encode(b"boss:fifteen-chars-ok").decode()}
    assert client.get("/api/admin/whoami", headers=h).status_code == 200


def test_admin_recovery_is_local_only(store, capsys):
    store.create_account_unchecked("boss", FAST.hash("a-long-admin-passphrase-1"), acc.ROLE_ADMIN)
    credential = issue(capsys, "boss")
    lan = TestClient(app, base_url="http://localhost", client=("192.168.1.5", 1))
    r = lan.post("/api/admin/recover", json={"name": "boss", "recovery_token": credential, "new_password": "fifteen-chars-ok"})
    assert r.status_code == 403


def test_there_is_no_admin_route_that_resets_a_player_password():
    from tests.api.test_api_admin import api_routes
    admin_paths = [r.path for r in api_routes() if r.path.startswith("/api/admin")]
    assert not [p for p in admin_paths if "reset" in p or ("players" in p and "password" in p)]
