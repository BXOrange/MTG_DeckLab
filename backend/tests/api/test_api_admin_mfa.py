"""PLR-9d / PLR-17 (second pass): admin MFA, remote admin in --online, account deletion lifecycle, MCP routes.

Reference: docs/concepts/15_ACCOUNT_SYSTEM_PLAN.md section 6 ([decided] 2026-11-04) and the section 8
*Admin* gates. Every store is a throwaway one and time is injected through a controllable clock:
no sleeps, nothing here touches ``data/*.db``.
"""

import base64
import importlib.util
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mtg_analyzer import config
from mtg_analyzer.api.admin_auth import get_admin_grants, get_admin_limiter
from mtg_analyzer.api.app import app, sweep_account_deletions
from mtg_analyzer.api.auth import get_login_limiter, get_password_hasher, get_signup_limiter
from mtg_analyzer.api.dependencies import (
    get_account_store, get_admin_jobs, get_deck_database, get_game_session_manager, get_player_asset_store,
)
from mtg_analyzer.models.decks.deck import Deck
from mtg_analyzer.services import account_store as acc
from mtg_analyzer.services import admin_service, mcp_credentials, totp
from mtg_analyzer.services.account_store import AccountStore
from mtg_analyzer.services.admin_grants import AdminGrants
from mtg_analyzer.services.admin_jobs import AdminJobs
from mtg_analyzer.services.deck_database import DeckDatabase
from mtg_analyzer.services.game_session import GameSessionManager
from mtg_analyzer.services.password_hasher import PasswordHasher
from mtg_analyzer.services.player_assets import PlayerAssetStore, bind_account_cleanup
from mtg_analyzer.services.rate_limiter import FailureLimiter
from tests.support.auth import use_test_key

pytestmark = pytest.mark.real_auth

FAST = PasswordHasher(n=2 ** 4)
ADMIN_PW = "a-long-admin-passphrase-1"
PLAYER_PW = "player pass 9!"
THROTTLE_LIMIT = 5
T0 = 1_700_000_000.0
STEP = config.TOTP_PERIOD_SECONDS
WRONG_CODE = "246813"
LOCAL = dict(base_url="http://localhost", client=("127.0.0.1", 50000))
#: A remote `--online` client over HTTPS (Host `testserver` is admitted by tests/conftest.py).
REMOTE = dict(base_url="https://testserver", client=("203.0.113.9", 50000))
REMOTE_HTTP = dict(base_url="http://testserver", client=("203.0.113.9", 50000))

manage_accounts = importlib.util.module_from_spec(
    importlib.util.spec_from_file_location(
        "manage_accounts_mfa", Path(__file__).resolve().parents[2] / "scripts" / "manage_accounts.py"
    )
)
manage_accounts.__spec__.loader.exec_module(manage_accounts)


class Clock:
    def __init__(self, now=T0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, steps=1):
        self.now += STEP * steps


def _returning(value):
    return lambda: value


@pytest.fixture
def env(tmp_path, monkeypatch):
    clock = Clock()
    store = AccountStore(tmp_path / "accounts.db", clock=clock, key=use_test_key(monkeypatch))
    decks = DeckDatabase(":memory:")
    assets = PlayerAssetStore(":memory:")
    bind_account_cleanup(store, assets)
    sessions = GameSessionManager()
    grants = AdminGrants(clock=clock)
    jobs = AdminJobs(runners={"card-pool": lambda report: {"updated": True}, "combos": lambda report: {}})
    limiters = {
        get_admin_limiter: FailureLimiter(THROTTLE_LIMIT, 60.0),
        get_login_limiter: FailureLimiter(50, 60.0),
        get_signup_limiter: FailureLimiter(50, 60.0),
    }
    overrides = {
        get_account_store: lambda: store, get_deck_database: lambda: decks,
        get_player_asset_store: lambda: assets, get_game_session_manager: lambda: sessions,
        get_admin_jobs: lambda: jobs, get_password_hasher: lambda: FAST, get_admin_grants: lambda: grants,
        **{dep: _returning(lim) for dep, lim in limiters.items()},
    }
    app.dependency_overrides.update(overrides)
    yield {"store": store, "decks": decks, "assets": assets, "sessions": sessions, "grants": grants,
           "clock": clock, "limiter": limiters[get_admin_limiter]}
    for dep in overrides:
        app.dependency_overrides.pop(dep, None)
    store.close()


@pytest.fixture
def client(env):
    return TestClient(app, **LOCAL)


@pytest.fixture
def online(monkeypatch):
    monkeypatch.setattr(config, "RUN_MODE", "online")


def basic(name="boss", password=ADMIN_PW, **extra):
    raw = f"{name}:{password}".encode("utf-8")
    return {"Authorization": "Basic " + base64.b64encode(raw).decode(), **extra}


def make_admin(env, name="boss", password=ADMIN_PW):
    return env["store"].create_account_unchecked(name, FAST.hash(password), acc.ROLE_ADMIN)


def make_player(env, name="Alice", password=PLAYER_PW):
    store = env["store"]
    token = store.create_invitation(acc.OPERATOR_CREATOR, acc.ROLE_PLAYER, enforce_limits=False)
    return store.create_account_with_invitation(name, FAST.hash(password), token, acc.ROLE_PLAYER)


def player_login(name="Alice", password=PLAYER_PW):
    c = TestClient(app, **LOCAL)
    r = c.post("/api/auth/login", json={"name": name, "password": password})
    assert r.status_code == 200
    c.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    return c


def code_for(secret, clock):
    return totp.totp(secret, clock.now)


def enrol(client, env, name="boss"):
    """Full enrolment over the API; returns (secret, recovery_codes, grant)."""
    started = client.post("/api/admin/mfa/enroll", headers=basic(name), json={})
    assert started.status_code == 200, started.text
    secret = started.json()["secret"]
    confirmed = client.post("/api/admin/mfa/confirm", headers=basic(name), json={"code": code_for(secret, env["clock"])})
    assert confirmed.status_code == 200, confirmed.text
    body = confirmed.json()
    return secret, body["recovery_codes"], body["grant"]


# ---------------------------------------------------------------------------
# Enrolment, login with a code, replay, recovery codes
# ---------------------------------------------------------------------------

class TestEnrolment:
    def test_loopback_without_mfa_still_works_and_enrolment_is_offered(self, client, env):
        make_admin(env)
        assert client.get("/api/admin/whoami", headers=basic()).json()["mfa_enrolled"] is False
        status = client.get("/api/admin/mfa", headers=basic()).json()
        assert status == {"enrolled": False, "pending": False, "recovery_codes_left": 0, "required": False}

    def test_enrolment_needs_the_password(self, client, env):
        make_admin(env)
        assert client.post("/api/admin/mfa/enroll", json={}).status_code == 401
        assert client.post("/api/admin/mfa/enroll", headers=basic(password="wrong-password-123456"), json={}).status_code == 401
        player = make_player(env)
        assert player and client.post("/api/admin/mfa/enroll", headers=basic("Alice", PLAYER_PW), json={}).status_code == 401

    def test_start_shows_secret_and_uri_as_text_and_confirm_needs_a_valid_code(self, client, env):
        admin = make_admin(env)
        started = client.post("/api/admin/mfa/enroll", headers=basic(), json={}).json()
        assert len(started["secret"]) == 32 and started["otpauth_uri"].startswith("otpauth://totp/")
        assert started["secret"] in started["otpauth_uri"] and started["replacing"] is False
        assert not env["store"].get_mfa(admin.player_uuid).enrolled  # nothing active before confirmation
        bad = client.post("/api/admin/mfa/confirm", headers=basic(), json={"code": "000000"})
        assert bad.status_code == 400 and bad.json()["detail"]["code"] == "invalid_code"
        assert not env["store"].get_mfa(admin.player_uuid).enrolled
        ok = client.post("/api/admin/mfa/confirm", headers=basic(), json={"code": code_for(started["secret"], env["clock"])})
        assert ok.status_code == 200
        assert len(ok.json()["recovery_codes"]) == 10 and ok.json()["grant"]
        assert env["store"].get_mfa(admin.player_uuid).enrolled

    def test_once_enrolled_the_password_alone_is_not_enough_on_loopback(self, client, env):
        make_admin(env)
        secret, _, grant = enrol(client, env)
        r = client.get("/api/admin/players", headers=basic())
        assert r.status_code == 401 and r.json()["detail"]["code"] == "admin_otp_required"
        assert client.get("/api/admin/players", headers=basic(**{"X-Admin-Grant": grant})).status_code == 200
        env["clock"].advance(3)
        assert client.get("/api/admin/players", headers=basic(**{"X-Admin-OTP": code_for(secret, env["clock"])})).status_code == 200

    def test_the_otp_alone_without_the_password_is_nothing(self, client, env):
        make_admin(env)
        secret, _, _ = enrol(client, env)
        env["clock"].advance(3)
        r = client.get("/api/admin/players", headers={"X-Admin-OTP": code_for(secret, env["clock"])})
        assert r.status_code == 401 and r.json()["detail"]["code"] == "admin_auth_required"

    def test_the_otp_header_is_single_use_per_time_step(self, client, env):
        make_admin(env)
        secret, _, _ = enrol(client, env)
        env["clock"].advance(3)
        headers = basic(**{"X-Admin-OTP": code_for(secret, env["clock"])})
        assert client.get("/api/admin/players", headers=headers).status_code == 200
        replay = client.get("/api/admin/players", headers=headers)
        assert replay.status_code == 401 and replay.json()["detail"]["code"] == "admin_auth_required"
        env["clock"].advance(1)
        assert client.get("/api/admin/players", headers=basic(**{"X-Admin-OTP": code_for(secret, env["clock"])})).status_code == 200

    def test_a_code_from_the_skew_window_works_and_a_far_one_does_not(self, client, env):
        make_admin(env)
        secret, _, _ = enrol(client, env)
        env["clock"].advance(5)
        near = totp.hotp(secret, totp.time_step(env["clock"].now) - config.TOTP_SKEW_STEPS)
        far = totp.hotp(secret, totp.time_step(env["clock"].now) - config.TOTP_SKEW_STEPS - 1)
        assert client.get("/api/admin/players", headers=basic(**{"X-Admin-OTP": far})).status_code == 401
        assert client.get("/api/admin/players", headers=basic(**{"X-Admin-OTP": near})).status_code == 200

    def test_wrong_codes_are_throttled_by_the_admin_limiter_and_audited(self, client, env):
        make_admin(env)
        enrol(client, env)
        statuses = [client.get("/api/admin/players", headers=basic(**{"X-Admin-OTP": WRONG_CODE})).status_code
                    for _ in range(THROTTLE_LIMIT + 1)]
        assert statuses[:THROTTLE_LIMIT] == [401] * THROTTLE_LIMIT and statuses[-1] == 429
        entries = env["store"].list_audit(limit=50)[0]
        assert any(e["action"] == "admin.auth" and "second factor" in e["result"] for e in entries)
        assert not any(WRONG_CODE in str(e) for e in entries)

    def test_recovery_codes_work_once_and_are_audited(self, client, env):
        make_admin(env)
        _, codes, _ = enrol(client, env)
        env["clock"].advance(1)
        ok = client.get("/api/admin/players", headers=basic(**{"X-Admin-OTP": codes[0]}))
        assert ok.status_code == 200
        again = client.get("/api/admin/players", headers=basic(**{"X-Admin-OTP": codes[0]}))
        assert again.status_code == 401
        assert any(e["action"] == "admin.recovery_code_used" for e in env["store"].list_audit(limit=50)[0])

    def test_recovery_codes_are_never_listed_again(self, client, env):
        make_admin(env)
        _, codes, grant = enrol(client, env)
        status = client.get("/api/admin/mfa", headers=basic(**{"X-Admin-Grant": grant}))
        assert status.json()["recovery_codes_left"] == 10 and codes[0] not in status.text
        for entry in env["store"].list_audit(limit=50)[0]:
            assert not any(c in str(entry) for c in codes)


class TestReplacement:
    def _setup(self, client, env):
        make_admin(env)
        secret, codes, grant = enrol(client, env)
        env["clock"].advance(3)
        return secret, codes, basic(**{"X-Admin-Grant": grant})

    def test_replacement_needs_a_current_code(self, client, env):
        secret, codes, headers = self._setup(client, env)
        missing = client.post("/api/admin/mfa/enroll", headers=headers, json={})
        assert missing.status_code == 400 and missing.json()["detail"]["code"] == "current_code_required"
        wrong = client.post("/api/admin/mfa/enroll", headers=headers, json={"current": "000000"})
        assert wrong.status_code == 400 and wrong.json()["detail"]["code"] == "invalid_code"
        ok = client.post("/api/admin/mfa/enroll", headers=headers, json={"current": code_for(secret, env["clock"])})
        assert ok.status_code == 200 and ok.json()["replacing"] is True and ok.json()["secret"] != secret

    def test_replacement_is_not_active_until_confirmed_then_the_old_secret_dies(self, client, env):
        secret, _, headers = self._setup(client, env)
        fresh = client.post("/api/admin/mfa/enroll", headers=headers,
                            json={"current": code_for(secret, env["clock"])}).json()["secret"]
        env["clock"].advance(3)
        assert client.get("/api/admin/players", headers=basic(**{"X-Admin-OTP": code_for(secret, env["clock"])})).status_code == 200
        env["clock"].advance(3)
        confirmed = client.post("/api/admin/mfa/confirm", headers=headers, json={"code": code_for(fresh, env["clock"])})
        assert confirmed.status_code == 200
        assert client.get("/api/admin/players", headers=headers).status_code == 401  # the old grant died with the old secret
        env["clock"].advance(3)
        assert client.get("/api/admin/players", headers=basic(**{"X-Admin-OTP": code_for(secret, env["clock"])})).status_code == 401
        env["clock"].advance(3)
        assert client.get("/api/admin/players", headers=basic(**{"X-Admin-OTP": code_for(fresh, env["clock"])})).status_code == 200

    def test_a_recovery_code_authorises_a_replacement(self, client, env):
        _, codes, headers = self._setup(client, env)
        r = client.post("/api/admin/mfa/enroll", headers=headers, json={"current": codes[1]})
        assert r.status_code == 200
        assert client.post("/api/admin/mfa/enroll", headers=headers, json={"current": codes[1]}).status_code == 400  # single use

    def test_a_replayed_current_code_is_refused(self, client, env):
        secret, _, headers = self._setup(client, env)
        code = code_for(secret, env["clock"])
        assert client.post("/api/admin/mfa/enroll", headers=headers, json={"current": code}).status_code == 200
        assert client.post("/api/admin/mfa/enroll", headers=headers, json={"current": code}).status_code == 400

    def test_new_recovery_codes_replace_the_old_ones(self, client, env):
        secret, old, headers = self._setup(client, env)
        r = client.post("/api/admin/mfa/recovery-codes", headers=headers, json={"current": code_for(secret, env["clock"])})
        assert r.status_code == 200
        new = r.json()["recovery_codes"]
        fresh_headers = basic(**{"X-Admin-Grant": r.json()["grant"]})
        assert client.post("/api/admin/mfa/enroll", headers=fresh_headers, json={"current": old[0]}).status_code == 400
        assert client.post("/api/admin/mfa/enroll", headers=fresh_headers, json={"current": new[0]}).status_code == 200

    def test_optional_mfa_can_be_turned_off_on_loopback_but_not_online(self, client, env, monkeypatch):
        secret, _, headers = self._setup(client, env)
        monkeypatch.setattr(config, "RUN_MODE", "online")
        assert client.post("/api/admin/mfa/disable", headers=headers, json={"current": "x"}).status_code == 409
        monkeypatch.setattr(config, "RUN_MODE", "lan")
        assert client.post("/api/admin/mfa/disable", headers=headers, json={"current": code_for(secret, env["clock"])}).status_code == 204
        assert client.get("/api/admin/players", headers=basic()).status_code == 200


class TestGrants:
    def test_a_grant_needs_a_verified_code_and_the_password_every_time(self, client, env):
        make_admin(env)
        secret, _, grant = enrol(client, env)
        assert client.get("/api/admin/players", headers={"X-Admin-Grant": grant}).status_code == 401  # no password
        assert client.post("/api/admin/mfa/grant", headers=basic(**{"X-Admin-Grant": grant})).status_code == 400  # not a code
        env["clock"].advance(3)
        issued = client.post("/api/admin/mfa/grant", headers=basic(**{"X-Admin-OTP": code_for(secret, env["clock"])}))
        assert issued.status_code == 200
        assert "set-cookie" not in issued.headers and not client.cookies  # a header, never a cookie

    def test_grants_expire_idle_and_absolute(self, client, env):
        make_admin(env)
        _, _, grant = enrol(client, env)
        headers = basic(**{"X-Admin-Grant": grant})
        env["clock"].now += config.ADMIN_GRANT_IDLE_SECONDS - 1
        assert client.get("/api/admin/players", headers=headers).status_code == 200  # slides the idle window
        env["clock"].now += config.ADMIN_GRANT_IDLE_SECONDS + 1
        assert client.get("/api/admin/players", headers=headers).status_code == 401
        _, _, grant2 = enrol_again(client, env)
        for _ in range(int(config.ADMIN_GRANT_ABSOLUTE_SECONDS // (config.ADMIN_GRANT_IDLE_SECONDS - 1)) + 2):
            env["clock"].now += config.ADMIN_GRANT_IDLE_SECONDS - 1
            client.get("/api/admin/players", headers=basic(**{"X-Admin-Grant": grant2}))
        assert client.get("/api/admin/players", headers=basic(**{"X-Admin-Grant": grant2})).status_code == 401

    def test_a_password_change_or_operator_reset_kills_grants(self, client, env):
        admin = make_admin(env)
        _, _, grant = enrol(client, env)
        headers = basic(**{"X-Admin-Grant": grant})
        env["store"].set_password(admin.player_uuid, FAST.hash("another-long-passphrase-2"))
        assert client.get("/api/admin/players", headers=basic(password="another-long-passphrase-2",
                                                              **{"X-Admin-Grant": grant})).status_code == 401
        assert headers

    def test_the_oldest_grant_is_evicted_past_the_cap(self, env):
        grants = env["grants"]
        tokens = []
        for _ in range(config.ADMIN_GRANT_MAX_PER_ADMIN + 1):
            env["clock"].now += 1
            tokens.append(grants.issue("u1", "peer", "b"))
        assert not grants.check(tokens[0], "u1", "peer", "b")
        assert grants.check(tokens[-1], "u1", "peer", "b")


def enrol_again(client, env):
    """A second enrolment cycle for an admin that disabled/lost its first (test helper)."""
    env["clock"].advance(5)
    secret = totp.new_secret()
    store = env["store"]
    admin = store.get_by_name("boss")
    store.clear_mfa(admin.player_uuid)
    store.begin_mfa_enrollment(admin.player_uuid, secret)
    codes = store.confirm_mfa_enrollment(admin.player_uuid, code_for(secret, env["clock"]))
    env["clock"].advance(1)
    r = client.post("/api/admin/mfa/grant", headers=basic(**{"X-Admin-OTP": code_for(secret, env["clock"])}))
    return secret, codes, r.json()["grant"]


# ---------------------------------------------------------------------------
# --online: remote admin only over HTTPS and only with MFA
# ---------------------------------------------------------------------------

class TestOnlineRemoteAdmin:
    def test_remote_over_plain_http_is_refused_even_with_valid_credentials(self, env, online):
        make_admin(env)
        remote = TestClient(app, **REMOTE_HTTP)
        for method, path in (("get", "/api/admin/state"), ("get", "/api/admin/whoami"), ("post", "/api/admin/mfa/enroll")):
            r = getattr(remote, method)(path, headers=basic())
            assert r.status_code == 403 and r.json()["detail"]["code"] == "admin_https_required", path

    def test_remote_over_https_without_mfa_can_do_nothing_but_enrol(self, env, online):
        make_admin(env)
        remote = TestClient(app, **REMOTE)
        for path in ("/api/admin/whoami", "/api/admin/players", "/api/admin/audit", "/api/admin/invitations", "/api/admin/jobs"):
            r = remote.get(path, headers=basic())
            assert r.status_code == 403 and r.json()["detail"]["code"] == "mfa_enrollment_required", path
        assert remote.get("/api/admin/mfa", headers=basic()).status_code == 200
        secret, _, grant = enrol(remote, env)
        assert remote.get("/api/admin/players", headers=basic(**{"X-Admin-Grant": grant})).status_code == 200

    def test_remote_over_https_with_mfa_needs_password_and_code_on_every_request(self, env, online):
        make_admin(env)
        remote = TestClient(app, **REMOTE)
        secret, _, grant = enrol(remote, env)
        assert remote.get("/api/admin/players", headers=basic()).status_code == 401
        assert remote.get("/api/admin/players", headers={"X-Admin-Grant": grant}).status_code == 401
        assert remote.get("/api/admin/players", headers=basic(password="wrong-passphrase-123456",
                                                              **{"X-Admin-Grant": grant})).status_code == 401
        assert remote.get("/api/admin/players", headers=basic(**{"X-Admin-Grant": grant})).status_code == 200
        env["clock"].advance(3)
        otp = {"X-Admin-OTP": code_for(secret, env["clock"])}
        assert remote.get("/api/admin/players", headers=basic(**otp)).status_code == 200
        assert remote.get("/api/admin/players", headers=basic(**otp)).status_code == 401  # replay

    def test_a_grant_is_bound_to_the_client_address(self, env, online):
        make_admin(env)
        remote = TestClient(app, **REMOTE)
        _, _, grant = enrol(remote, env)
        elsewhere = TestClient(app, base_url="https://testserver", client=("198.51.100.7", 4000))
        assert elsewhere.get("/api/admin/players", headers=basic(**{"X-Admin-Grant": grant})).status_code == 401
        assert remote.get("/api/admin/players", headers=basic(**{"X-Admin-Grant": grant})).status_code == 200

    def test_remote_failures_are_throttled_per_source_as_well(self, env, online):
        make_admin(env)
        remote = TestClient(app, **REMOTE)
        for _ in range(THROTTLE_LIMIT):
            remote.get("/api/admin/state", headers=basic(password="wrong-passphrase-123456"))
            remote.get("/api/admin/whoami", headers=basic("ghost-" + str(_), "x"))
        assert remote.get("/api/admin/whoami", headers=basic("another", "x")).status_code == 429

    def test_loopback_in_online_still_requires_mfa(self, client, env, online):
        make_admin(env)
        r = client.get("/api/admin/players", headers=basic())
        assert r.status_code == 403 and r.json()["detail"]["code"] == "mfa_enrollment_required"

    def test_behind_a_tls_proxy_forwarded_proto_counts_only_when_declared(self, env, online, monkeypatch):
        make_admin(env)
        proxied = TestClient(app, base_url="http://testserver", client=("127.0.0.1", 50000))  # BUG-52: trusted proxy peer
        headers = basic(**{"X-Forwarded-Proto": "https", "X-Forwarded-For": "198.51.100.7"})
        assert proxied.get("/api/admin/mfa", headers=headers).status_code == 403  # proxy mode not declared
        monkeypatch.setattr(config, "BEHIND_TLS_PROXY", True)
        assert proxied.get("/api/admin/mfa", headers=headers).status_code == 200
        plain = basic(**{"X-Forwarded-Proto": "http", "X-Forwarded-For": "198.51.100.7"})
        assert proxied.get("/api/admin/mfa", headers=plain).status_code == 403

    @pytest.mark.parametrize("mode", ["lan", "localdev"])
    def test_outside_online_remote_admin_stays_refused_even_over_https(self, env, monkeypatch, mode):
        monkeypatch.setattr(config, "RUN_MODE", mode)
        make_admin(env)
        for kw in (REMOTE, REMOTE_HTTP, dict(base_url="http://localhost", client=("192.168.1.7", 5))):
            r = TestClient(app, **kw).get("/api/admin/whoami", headers=basic())
            assert r.status_code == 403 and r.json()["detail"]["code"] == "admin_local_only"

    def test_admin_signup_in_online_leaves_the_account_inactive_until_mfa_is_enrolled(self, env, online):
        token = env["store"].create_invitation(acc.OPERATOR_CREATOR, acc.ROLE_ADMIN, enforce_limits=False)
        remote = TestClient(app, **REMOTE)
        r = remote.post("/api/admin/signup", json={"name": "newadmin", "password": ADMIN_PW, "invitation": token})
        assert r.status_code == 201 and r.json()["mfa_enrollment_required"] is True
        inactive = remote.get("/api/admin/players", headers=basic("newadmin"))
        assert inactive.status_code == 403 and inactive.json()["detail"]["code"] == "mfa_enrollment_required"
        _, _, grant = enrol(remote, env, "newadmin")
        assert remote.get("/api/admin/players", headers=basic("newadmin", **{"X-Admin-Grant": grant})).status_code == 200

    def test_no_cookie_and_no_store_on_remote_responses(self, env, online):
        make_admin(env)
        remote = TestClient(app, **REMOTE)
        r = remote.get("/api/admin/mfa", headers=basic())
        assert "set-cookie" not in r.headers and r.headers["cache-control"] == "no-store"

    def test_the_admin_page_is_served_remotely_only_over_https_in_online(self, env, online):
        # the proxy gate; the upstream is unreachable in this test, so anything but 403 means "admitted"
        assert TestClient(app, **REMOTE_HTTP).get("/admin").status_code == 403
        assert TestClient(app, **REMOTE).get("/admin").status_code != 403


# ---------------------------------------------------------------------------
# First admin in --online (OS-operator command)
# ---------------------------------------------------------------------------

class TestFirstAdminCommand:
    def test_create_admin_issues_a_one_time_credential_and_no_password(self, env, monkeypatch, tmp_path, capsys):
        monkeypatch.setattr(config, "ACCOUNTS_DB_PATH", env["store"]._path)
        assert manage_accounts.main(["create-admin", "firstadmin"]) == 0
        out = capsys.readouterr().out
        token = out.split("shown only once:")[1].split()[0]
        admin = env["store"].get_by_name("firstadmin")
        assert admin.role == acc.ROLE_ADMIN and admin.password_hash == acc.UNUSABLE_PASSWORD_HASH
        assert token not in repr(env["store"]._conn.execute("SELECT * FROM recovery_credentials").fetchall())
        assert any(e["actor"] == "operator" and e["action"] == "admin.created" for e in env["store"].list_audit(limit=10)[0])

    def test_the_credential_sets_the_password_then_mfa_is_forced_online(self, env, monkeypatch, online, capsys):
        monkeypatch.setattr(config, "ACCOUNTS_DB_PATH", env["store"]._path)
        manage_accounts.main(["create-admin", "firstadmin"])
        token = capsys.readouterr().out.split("shown only once:")[1].split()[0]
        remote = TestClient(app, **REMOTE)
        assert remote.get("/api/admin/mfa", headers=basic("firstadmin", ADMIN_PW)).status_code == 401  # nothing usable yet
        r = remote.post("/api/admin/recover", json={"name": "firstadmin", "recovery_token": token, "new_password": ADMIN_PW})
        assert r.status_code == 204
        assert remote.post("/api/admin/recover", json={"name": "firstadmin", "recovery_token": token,
                                                       "new_password": ADMIN_PW}).status_code == 400  # single use
        blocked = remote.get("/api/admin/players", headers=basic("firstadmin"))
        assert blocked.status_code == 403 and blocked.json()["detail"]["code"] == "mfa_enrollment_required"
        _, _, grant = enrol(remote, env, "firstadmin")
        assert remote.get("/api/admin/players", headers=basic("firstadmin", **{"X-Admin-Grant": grant})).status_code == 200

    @pytest.mark.parametrize("name", ["admin", "x", "a:b", "root"])
    def test_invalid_or_reserved_names_are_refused(self, env, monkeypatch, capsys, name):
        monkeypatch.setattr(config, "ACCOUNTS_DB_PATH", env["store"]._path)
        assert manage_accounts.main(["create-admin", name]) == 1
        assert env["store"].count_accounts("admin") == 0

    def test_an_existing_name_is_refused(self, env, monkeypatch):
        monkeypatch.setattr(config, "ACCOUNTS_DB_PATH", env["store"]._path)
        make_player(env, "Alice")
        assert manage_accounts.main(["create-admin", "alice"]) == 1

    def test_reset_mfa_removes_the_authenticator(self, client, env, monkeypatch, capsys):
        monkeypatch.setattr(config, "ACCOUNTS_DB_PATH", env["store"]._path)
        admin = make_admin(env)
        enrol(client, env)
        assert manage_accounts.main(["reset-mfa", "boss"]) == 0
        assert not env["store"].get_mfa(admin.player_uuid).enrolled
        assert client.get("/api/admin/players", headers=basic()).status_code == 200  # optional again on loopback
        assert manage_accounts.main(["reset-mfa", "ghost"]) == 1


# ---------------------------------------------------------------------------
# Account deletion lifecycle
# ---------------------------------------------------------------------------

class TestDeletionLifecycle:
    def _populate(self, env, alice):
        env["decks"].save_private(Deck(name="secret", mainboard_text="1 Island"), alice.player_uuid)
        env["assets"].save_token_image(alice.player_uuid, "Goblin", "image/png", b"\x89PNG0")

    def test_request_needs_a_session_the_password_and_csrf(self, env):
        make_player(env)
        assert TestClient(app, **LOCAL).post("/api/auth/delete-account", json={"password": PLAYER_PW}).status_code == 401
        c = player_login()
        no_csrf = TestClient(app, **LOCAL)
        no_csrf.cookies.update(c.cookies)
        assert no_csrf.post("/api/auth/delete-account", json={"password": PLAYER_PW}).status_code == 403
        wrong = c.post("/api/auth/delete-account", json={"password": "not the password"})
        assert wrong.status_code == 401 and env["store"].get_by_name("Alice").deletion_requested_at is None

    def test_request_disables_at_once_and_refuses_login_generically(self, env):
        alice = make_player(env)
        c = player_login()
        r = c.post("/api/auth/delete-account", json={"password": PLAYER_PW})
        assert r.status_code == 200 and r.json()["grace_days"] == config.ACCOUNT_DELETION_GRACE_SECONDS / 86400
        stored = env["store"].get(alice.player_uuid)
        assert stored.disabled and stored.deletion_requested_at == T0
        assert r.json()["deletion_due_at"] == T0 + config.ACCOUNT_DELETION_GRACE_SECONDS
        assert c.get("/api/auth/me").json() == {"authenticated": False}
        assert env["store"].list_sessions(alice.player_uuid) == []
        refused = TestClient(app, **LOCAL).post("/api/auth/login", json={"name": "Alice", "password": PLAYER_PW})
        ghost = TestClient(app, **LOCAL).post("/api/auth/login", json={"name": "Nobody", "password": PLAYER_PW})
        assert refused.status_code == 401 and refused.json() == ghost.json()  # indistinguishable
        assert env["store"].get_by_name("Alice").role == acc.ROLE_PLAYER

    def test_request_is_audited_and_the_default_localuser_is_protected(self, env):
        make_player(env)
        player_login().post("/api/auth/delete-account", json={"password": PLAYER_PW})
        entries = env["store"].list_audit(limit=10)[0]
        assert any(e["actor"] == "Alice" and e["action"] == "account.deletion_requested" for e in entries)
        assert PLAYER_PW not in repr(entries)
        local = env["store"].ensure_default_local()
        assert env["store"].request_deletion(local.player_uuid) is None

    def test_admin_sees_the_pending_deletion_with_its_due_date(self, client, env):
        make_admin(env)
        alice = make_player(env)
        player_login().post("/api/auth/delete-account", json={"password": PLAYER_PW})
        body = client.get("/api/admin/pending-deletions", headers=basic()).json()
        assert body["grace_days"] == config.ACCOUNT_DELETION_GRACE_SECONDS / 86400
        assert body["pending"] == [{"player_uuid": alice.player_uuid, "name": "Alice", "requested_at": T0,
                                    "due_at": T0 + config.ACCOUNT_DELETION_GRACE_SECONDS}]
        listing = client.get("/api/admin/players", headers=basic()).json()["players"][0]
        assert listing["disabled"] is True and listing["deletion_due_at"] == body["pending"][0]["due_at"]
        assert client.get("/api/admin/pending-deletions").status_code == 401

    def test_pending_names_are_returned_as_data_not_markup(self, client, env):
        make_admin(env)
        evil = '<img src=x onerror="alert(1)">'
        make_player(env, evil)
        player_login(evil).post("/api/auth/delete-account", json={"password": PLAYER_PW})
        r = client.get("/api/admin/pending-deletions", headers=basic())
        assert r.headers["content-type"].startswith("application/json")
        assert r.json()["pending"][0]["name"] == evil

    def test_re_enabling_within_the_grace_period_cancels_the_deletion(self, client, env):
        make_admin(env)
        alice = make_player(env)
        self._populate(env, alice)
        player_login().post("/api/auth/delete-account", json={"password": PLAYER_PW})
        env["clock"].now += config.ACCOUNT_DELETION_GRACE_SECONDS - 10
        r = client.post(f"/api/admin/players/{alice.player_uuid}/enable", headers=basic())
        assert r.status_code == 204
        restored = env["store"].get(alice.player_uuid)
        assert not restored.disabled and restored.deletion_requested_at is None
        assert client.get("/api/admin/pending-deletions", headers=basic()).json()["pending"] == []
        env["clock"].now += config.ACCOUNT_DELETION_GRACE_SECONDS * 2
        assert admin_service.finalize_due_deletions(env["store"], env["decks"], env["assets"], env["sessions"]) == []
        assert env["decks"].count_private(alice.player_uuid) == 1
        player_login()  # the player can sign in again
        assert any(e["action"] == "player.deletion_cancelled" for e in env["store"].list_audit(limit=20)[0])

    def test_nothing_is_deleted_before_the_grace_period_ends(self, env):
        alice = make_player(env)
        self._populate(env, alice)
        player_login().post("/api/auth/delete-account", json={"password": PLAYER_PW})
        env["clock"].now += config.ACCOUNT_DELETION_GRACE_SECONDS - 1
        assert admin_service.finalize_due_deletions(env["store"], env["decks"], env["assets"], env["sessions"]) == []
        assert env["store"].get(alice.player_uuid) is not None and env["decks"].count_private(alice.player_uuid) == 1

    def test_after_the_grace_period_the_cascade_and_the_tombstone_run(self, client, env):
        alice = make_player(env)
        bob = make_player(env, "Bobby")
        self._populate(env, alice)
        env["decks"].save_private(Deck(name="bobs"), bob.player_uuid)
        player_login().post("/api/auth/delete-account", json={"password": PLAYER_PW})
        env["clock"].now += config.ACCOUNT_DELETION_GRACE_SECONDS + 1
        assert admin_service.finalize_due_deletions(env["store"], env["decks"], env["assets"], env["sessions"]) == ["Alice"]
        assert env["store"].get(alice.player_uuid) is None
        assert env["decks"].count_private(alice.player_uuid) == 0
        assert sum(env["assets"].count_for_owner(alice.player_uuid).values()) == 0
        assert env["decks"].count_private(bob.player_uuid) == 1
        assert env["store"].drain_deleted() == [alice.player_uuid]  # the sweeper frees the seat
        token = env["store"].create_invitation(acc.OPERATOR_CREATOR, acc.ROLE_PLAYER, enforce_limits=False)
        taken = client.post("/api/auth/signup", json={"name": "alice", "password": PLAYER_PW, "invitation": token})
        assert taken.status_code == 409 and taken.json()["detail"]["code"] == "name_taken"  # name tombstone
        deleted = [e for e in env["store"].list_audit(limit=20)[0] if e["action"] == "player.deleted"]
        assert deleted and deleted[0]["actor"] == "system" and deleted[0]["target"] == "player:Alice"

    def test_the_startup_and_periodic_sweep_entry_point_uses_the_app_stores(self, env, monkeypatch):
        import importlib
        app_module = importlib.import_module("mtg_analyzer.api.app")
        dependencies = importlib.import_module("mtg_analyzer.api.dependencies")
        monkeypatch.setattr(app_module, "get_account_store", lambda: env["store"])
        monkeypatch.setattr(app_module, "get_game_session_manager", lambda: env["sessions"])
        monkeypatch.setattr(dependencies, "get_deck_database", lambda: env["decks"])
        monkeypatch.setattr(dependencies, "get_player_asset_store", lambda: env["assets"])
        alice = make_player(env)
        player_login().post("/api/auth/delete-account", json={"password": PLAYER_PW})
        env["clock"].now += config.ACCOUNT_DELETION_GRACE_SECONDS + 1
        assert sweep_account_deletions() == ["Alice"]
        assert env["store"].get(alice.player_uuid) is None

    def test_the_grace_period_is_the_named_configurable_constant(self):
        assert config.ACCOUNT_DELETION_GRACE_SECONDS == 7 * 24 * 3600
        assert config.ACCOUNT_DELETION_SWEEP_SECONDS > 0

    def test_an_admin_can_still_delete_a_pending_account_immediately(self, client, env):
        make_admin(env)
        alice = make_player(env)
        player_login().post("/api/auth/delete-account", json={"password": PLAYER_PW})
        r = client.post(f"/api/admin/players/{alice.player_uuid}/delete", headers=basic(), json={"confirm_name": "Alice"})
        assert r.status_code == 200 and env["store"].get(alice.player_uuid) is None

    def test_the_sweep_survives_one_failing_account(self, env, monkeypatch):
        make_player(env, "Alice")
        make_player(env, "Bobby")
        for name in ("Alice", "Bobby"):
            env["store"].request_deletion(env["store"].get_by_name(name).player_uuid)
        env["clock"].now += config.ACCOUNT_DELETION_GRACE_SECONDS + 1
        real = admin_service.delete_player

        def flaky(accounts, decks, assets, sessions, account):
            if account.name == "Alice":
                raise RuntimeError("disk")
            return real(accounts, decks, assets, sessions, account)

        monkeypatch.setattr(admin_service, "delete_player", flaky)
        assert admin_service.finalize_due_deletions(env["store"], env["decks"], env["assets"], env["sessions"]) == ["Bobby"]
        assert env["store"].get_by_name("Alice") is not None  # still pending, retried next sweep


# ---------------------------------------------------------------------------
# MCP settings routes (PLR-17)
# ---------------------------------------------------------------------------

class TestMcpSettingsRoutes:
    @pytest.fixture(autouse=True)
    def _token(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mcp_credentials, "_path", lambda: tmp_path / "mcp_token")
        self.token = mcp_credentials.rotate_token()

    def test_anonymous_is_denied_everywhere(self, client):
        assert client.get("/api/mcp-settings").status_code == 401
        assert client.post("/api/mcp-settings/setup").status_code == 401
        assert client.post("/api/mcp-settings/rotate").status_code == 401

    def test_a_player_may_read_status_and_setup(self, env):
        make_player(env)
        player = player_login()
        status = player.get("/api/mcp-settings")
        assert status.status_code == 200 and status.json()["configured"] is True
        assert self.token not in status.text
        setup = player.post("/api/mcp-settings/setup")
        assert setup.status_code == 200 and setup.json()["server_token"] == self.token

    def test_a_player_cannot_rotate_by_direct_call(self, env):
        make_player(env)
        player = player_login()
        for headers in ({}, basic("Alice", PLAYER_PW)):
            r = player.post("/api/mcp-settings/rotate", headers=headers)
            assert r.status_code in (401, 403)
        assert mcp_credentials.read_token() == self.token

    def test_admin_credentials_do_not_read_the_player_routes(self, client, env):
        make_admin(env)
        assert client.get("/api/mcp-settings", headers=basic()).status_code == 401

    def test_an_admin_on_loopback_can_rotate_and_it_is_audited_without_the_token(self, client, env):
        make_admin(env)
        r = client.post("/api/mcp-settings/rotate", headers=basic())
        assert r.status_code == 200
        new = r.json()["server_token"]
        assert new != self.token and mcp_credentials.read_token() == new
        entries = env["store"].list_audit(limit=10)[0]
        assert any(e["action"] == "mcp.token_rotated" and e["actor"] == "boss" for e in entries)
        assert new not in repr(entries) and self.token not in repr(entries)

    def test_rotation_needs_the_second_factor_once_enrolled(self, client, env):
        make_admin(env)
        _, _, grant = enrol(client, env)
        assert client.post("/api/mcp-settings/rotate", headers=basic()).status_code == 401
        assert client.post("/api/mcp-settings/rotate", headers=basic(**{"X-Admin-Grant": grant})).status_code == 200

    def test_a_lan_client_cannot_rotate_even_as_admin(self, env):
        make_admin(env)
        lan = TestClient(app, base_url="http://localhost", client=("192.168.1.7", 5))
        assert lan.post("/api/mcp-settings/rotate", headers=basic()).status_code == 403
        assert mcp_credentials.read_token() == self.token

    def test_the_player_ui_has_no_rotate_button(self):
        root = Path(__file__).resolve().parents[3] / "frontend" / "src" / "js"
        view = (root / "connectionSettingsView.js").read_text(encoding="utf-8")
        assert "mcp-generate" not in view and "rotateMcpToken" not in view
        assert "rotateMcpToken" not in (root / "api.js").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Route inventory: every admin route stays behind the shared gate
# ---------------------------------------------------------------------------

def test_every_admin_route_refuses_anonymous_callers(env):
    from tests.api.test_api_admin import api_routes

    anonymous = TestClient(app, **LOCAL)
    public = {"/api/admin/state", "/api/admin/signup", "/api/admin/recover"}  # pre-login forms, local surface only
    seen = 0
    for route in api_routes():
        if not route.path.startswith("/api/admin") or route.path in public:
            continue
        for method in route.methods - {"HEAD", "OPTIONS"}:
            path = route.path.replace("{player_uuid}", "x").replace("{invitation_id}", "x").replace("{deck_id}", "x").replace("{job_id}", "x")
            r = anonymous.request(method, path, json={})
            assert r.status_code in (401, 404), (method, route.path, r.status_code)
            seen += 1
    assert seen > 20
