"""PLR-19: a genuinely local admin request never needs the authenticator code, in every run mode.

Remote admin (HTTPS + password + code in ``--online``) is unchanged. Stores are throwaway ones
(fixtures of ``test_api_admin_mfa``); nothing here touches ``data/*.db``.
"""

import pytest
from fastapi.testclient import TestClient

from mtg_analyzer import config
from mtg_analyzer.api.app import app
from mtg_analyzer.services import account_store as acc
from tests.api.test_api_admin_mfa import (  # noqa: F401 - fixtures are imported by name
    ADMIN_PW, FAST, LOCAL, REMOTE, REMOTE_HTTP, basic, code_for, enrol, env, make_admin, online,
)

pytestmark = pytest.mark.real_auth


@pytest.mark.parametrize("mode", ["lan", "localdev", "online"])
def test_local_request_needs_no_code_even_when_enrolled(env, monkeypatch, mode):
    monkeypatch.setattr(config, "RUN_MODE", mode)
    make_admin(env)
    local = TestClient(app, **LOCAL)
    enrol(local, env)  # an enrolled admin: still no code on a local request
    assert local.get("/api/admin/players", headers=basic()).status_code == 200
    assert local.get("/api/admin/whoami", headers=basic()).json()["mfa_enrolled"] is True


def test_online_remote_without_code_is_refused_and_with_code_works(env, online):
    make_admin(env)
    secret, _, _ = enrol(TestClient(app, **LOCAL), env)
    remote = TestClient(app, **REMOTE)
    refused = remote.get("/api/admin/players", headers=basic())
    assert refused.status_code == 401 and refused.json()["detail"]["code"] == "admin_otp_required"
    env["clock"].advance(3)
    assert remote.get("/api/admin/players", headers=basic(**{"X-Admin-OTP": code_for(secret, env["clock"])})).status_code == 200


def test_remote_over_plain_http_is_still_refused(env, online):
    make_admin(env)
    assert TestClient(app, **REMOTE_HTTP).get("/api/admin/players", headers=basic()).status_code == 403


@pytest.mark.parametrize("mode", ["lan", "localdev"])
def test_remote_is_still_refused_outside_online(env, monkeypatch, mode):
    monkeypatch.setattr(config, "RUN_MODE", mode)
    make_admin(env)
    assert TestClient(app, **REMOTE).get("/api/admin/players", headers=basic()).status_code == 403


def test_locally_signed_up_online_admin_works_locally_and_must_enrol_before_remote_use(env, online):
    store = env["store"]
    token = store.create_invitation(acc.OPERATOR_CREATOR, acc.ROLE_ADMIN, enforce_limits=False)
    local = TestClient(app, **LOCAL)
    created = local.post("/api/admin/signup", json={"name": "newbie", "password": ADMIN_PW, "invitation": token})
    assert created.status_code == 201
    assert created.json() == {"name": "newbie", "mfa_enrollment_required": False, "mfa_enrollment_required_for_remote": True}
    assert local.get("/api/admin/players", headers=basic("newbie")).status_code == 200  # local: password only
    remote = TestClient(app, **REMOTE)
    refused = remote.get("/api/admin/players", headers=basic("newbie"))
    assert refused.status_code == 403 and refused.json()["detail"]["code"] == "mfa_enrollment_required"
    secret, _, grant = enrol(remote, env, "newbie")  # enrolment routes stay open remotely
    assert remote.get("/api/admin/players", headers=basic("newbie", **{"X-Admin-Grant": grant})).status_code == 200


def test_remote_signup_reports_that_enrolment_is_due(env, online):
    token = env["store"].create_invitation(acc.OPERATOR_CREATOR, acc.ROLE_ADMIN, enforce_limits=False)
    created = TestClient(app, **REMOTE).post(
        "/api/admin/signup", json={"name": "far", "password": ADMIN_PW, "invitation": token})
    assert created.status_code == 201 and created.json()["mfa_enrollment_required"] is True


def test_state_tells_the_page_whether_this_connection_needs_a_code(env, online):
    assert TestClient(app, **LOCAL).get("/api/admin/state").json()["second_factor_required"] is False
    assert TestClient(app, **REMOTE).get("/api/admin/state").json()["second_factor_required"] is True


def test_mfa_enrolment_stays_available_locally(env, online):
    make_admin(env)
    local = TestClient(app, **LOCAL)
    assert local.get("/api/admin/mfa", headers=basic()).json()["enrolled"] is False
    enrol(local, env)
    assert local.get("/api/admin/mfa", headers=basic()).json()["enrolled"] is True


def test_a_wrong_password_is_still_refused_locally(env, online):
    make_admin(env)
    r = TestClient(app, **LOCAL).get("/api/admin/players", headers=basic(password="not-the-password-123"))
    assert r.status_code == 401
