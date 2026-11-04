"""PLR-9e: security-event logging, sanitization and `no-store` on private responses.

Reference: docs/concepts/15_ACCOUNT_SYSTEM_PLAN.md section 7. Throwaway stores only.
"""

import logging
import stat
import sys

import pytest
from fastapi.testclient import TestClient

from mtg_analyzer import config
from mtg_analyzer.api.app import app
from mtg_analyzer.api.auth import get_login_limiter, get_password_hasher, get_signup_limiter
from mtg_analyzer.api.dependencies import get_account_store
from mtg_analyzer.security_headers import NO_STORE_PREFIXES, needs_no_store
from mtg_analyzer.services import security_log
from mtg_analyzer.services.account_store import AccountStore
from mtg_analyzer.services.password_hasher import PasswordHasher
from mtg_analyzer.services.rate_limiter import FailureLimiter

pytestmark = pytest.mark.real_auth

PW = "correct horse 9!"
FAST = PasswordHasher(n=2 ** 4)


class Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record):
        self.lines.append(record.getMessage())


@pytest.fixture
def lines():
    handler = Capture()
    logger = logging.getLogger(security_log.LOGGER_NAME)
    logger.addHandler(handler)
    yield handler.lines
    logger.removeHandler(handler)


@pytest.fixture
def store(tmp_path):
    s = AccountStore(tmp_path / "accounts.db")
    app.dependency_overrides[get_account_store] = lambda: s
    app.dependency_overrides[get_password_hasher] = lambda: FAST
    login = FailureLimiter(3, 60.0)
    app.dependency_overrides[get_login_limiter] = lambda: login
    app.dependency_overrides[get_signup_limiter] = lambda: FailureLimiter(50, 60.0)
    yield s
    for dep in (get_account_store, get_password_hasher, get_login_limiter, get_signup_limiter):
        app.dependency_overrides.pop(dep, None)


@pytest.fixture
def client(store):
    return TestClient(app)


def _signup(client, store, name="Alice"):
    admin = store.get_by_name("seed") or store.create_account_unchecked("seed", FAST.hash("x"), "admin")
    token = store.create_invitation(admin.player_uuid, "player", enforce_limits=False)
    resp = client.post("/api/auth/signup", json={"name": name, "password": PW, "invitation": token})
    return resp, token


def test_login_outcomes_are_logged_without_secrets(client, store, lines):
    resp, invitation = _signup(client, store)
    assert resp.status_code == 201
    cookie = client.cookies.get(config_cookie())
    csrf = resp.json()["csrf_token"]
    fresh = TestClient(app)  # no session cookie, so no CSRF requirement on the login post
    fresh.post("/api/auth/login", json={"name": "Alice", "password": "wrong wrong 1!"})
    fresh.post("/api/auth/login", json={"name": "Alice", "password": PW})
    text = "\n".join(lines)
    assert 'event=auth.signup outcome="success"' in text
    assert 'event=auth.login outcome="failure"' in text and 'outcome="success"' in text
    assert "event=session.created" in text
    for secret in (PW, "wrong wrong 1!", invitation, cookie, csrf):
        assert secret and secret not in text


def config_cookie():
    from mtg_analyzer.api.auth import session_cookie_name

    return session_cookie_name()


def test_throttle_and_authorization_refusals_are_logged(client, store, lines):
    for _ in range(4):
        client.post("/api/auth/login", json={"name": "Nobody", "password": "x" * 12})
    anonymous = TestClient(app)
    assert anonymous.get("/api/auth/sessions").status_code == 401
    text = "\n".join(lines)
    assert 'outcome="throttled"' in text
    assert 'event=authz.refused method="GET" route="/api/auth/sessions" status="401"' in text


def test_session_lifecycle_is_logged(client, store, lines):
    resp, _ = _signup(client, store)
    csrf = {"X-CSRF-Token": resp.json()["csrf_token"]}
    client.post("/api/auth/logout", headers=csrf)
    text = "\n".join(lines)
    assert "event=session.revoked" in text and 'reason="logout"' in text


def test_audit_entries_are_mirrored(store, lines):
    store.record_audit("operator", "recovery.issued", "player:Alice")
    assert 'event=audit actor="operator" action="recovery.issued" target="player:Alice" outcome="ok"' in "\n".join(lines)


def test_values_are_single_line_and_bounded():
    line = security_log.format_event("x", {"name": "evil\nevent=forged\r\x00" + "A" * 500})
    assert "\n" not in line and "\r" not in line and "\x00" not in line
    assert len(line) < security_log.VALUE_MAX + 40
    assert security_log.clean('say "hi"') == "say 'hi'"


@pytest.mark.parametrize("field", ["password", "session_token", "Cookie", "csrf", "totp_secret", "otp", "recovery_code", "authorization", "body"])
def test_secret_looking_fields_are_refused(field):
    with pytest.raises(ValueError):
        security_log.format_event("x", {field: "value"})


def test_ids_in_routes_are_collapsed():
    assert security_log.route_of("/api/decks/123/copy") == "/api/decks/{id}/copy"
    assert security_log.route_of("/api/auth/sessions/0123456789abcdef") == "/api/auth/sessions/{id}"


def test_private_responses_are_no_store_even_on_errors(client, store):
    for path in ("/api/auth/me", "/api/auth/sessions", "/api/decks", "/api/me/sleeves", "/api/admin/state", "/api/mcp-settings"):
        response = client.get(path)
        assert response.headers.get("cache-control") == "no-store", path


def test_public_card_routes_stay_cacheable():
    assert not needs_no_store("/api/cards/search")
    assert not needs_no_store("/api/decksomething")  # prefix match is on whole segments
    assert needs_no_store("/api/decks/5") and needs_no_store("/admin")
    assert all(p.startswith("/") for p in NO_STORE_PREFIXES)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX modes")
def test_security_log_file_is_private_and_rotates(tmp_path, monkeypatch):
    path = tmp_path / "logs" / "security.log"
    monkeypatch.setattr(config, "SECURITY_LOG_FILE", str(path))
    monkeypatch.setattr(config, "SECURITY_LOG_MAX_BYTES", 400)
    monkeypatch.setattr(config, "SECURITY_LOG_BACKUPS", 2)
    logger = logging.getLogger(security_log.LOGGER_NAME)
    before = list(logger.handlers)
    monkeypatch.setattr(security_log, "_configured", False)
    try:
        for index in range(40):
            security_log.event("probe", index=index, padding="x" * 40)
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
        rotated = sorted(p.name for p in path.parent.iterdir())
        assert rotated == ["security.log", "security.log.1", "security.log.2"]  # bounded by the backup count
        assert all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in path.parent.iterdir())
    finally:
        for handler in list(logger.handlers):
            if handler not in before:
                logger.removeHandler(handler)
                handler.close()
