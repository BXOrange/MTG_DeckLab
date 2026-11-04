"""Magic-byte upload check and security response headers (BUG-44)."""

import pytest
from fastapi.testclient import TestClient

from mtg_analyzer.api.app import app
from mtg_analyzer.api.dependencies import get_player_asset_store
from mtg_analyzer.security_headers import ASSET_CSP, STATIC_SECURITY_HEADERS, csp_for
from mtg_analyzer.services.player_assets import PlayerAssetStore

GOOD = {
    "image/png": b"\x89PNG\r\n\x1a\n" + b"data",
    "image/jpeg": b"\xff\xd8\xff\xe0" + b"data",
    "image/gif": b"GIF89a" + b"data",
    "image/webp": b"RIFF\x04\x00\x00\x00WEBPVP8 ",
}
EXPECTED_STATIC = {
    "x-content-type-options": "nosniff",
    "referrer-policy": "same-origin",
    "x-frame-options": "DENY",
}


@pytest.fixture
def client():
    store = PlayerAssetStore(":memory:")
    app.dependency_overrides[get_player_asset_store] = lambda: store
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_player_asset_store, None)
        store.close()


def _post(client, content_type, data):
    return client.post(
        "/api/me/sleeves", data={"label": "s"}, files={"file": ("a", data, content_type)}
    )


@pytest.mark.parametrize("content_type", sorted(GOOD))
def test_matching_signature_is_accepted(client, content_type):
    assert _post(client, content_type, GOOD[content_type]).status_code == 200


@pytest.mark.parametrize("content_type", sorted(GOOD))
def test_other_types_bytes_and_html_are_rejected(client, content_type):
    for other, data in GOOD.items():
        if other != content_type:
            assert _post(client, content_type, data).status_code == 400
    assert _post(client, content_type, b"<script>alert(1)</script>").status_code == 400


def test_webp_needs_both_riff_and_webp_markers(client):
    assert _post(client, "image/webp", b"RIFF\x04\x00\x00\x00WAVE").status_code == 400


def test_token_image_upload_is_checked_too(client):
    bad = client.post(
        "/api/me/token-images", data={"token_name": "t"},
        files={"file": ("a", b"<svg/>", "image/png")},
    )
    assert bad.status_code == 400


def test_headers_on_api_response(client):
    res = client.get("/api/health")
    for name, value in EXPECTED_STATIC.items():
        assert res.headers[name] == value
    assert res.headers["content-security-policy"] == csp_for("testserver")


def test_headers_on_guard_refusal(client):
    res = client.get("/api/health", headers={"Host": "attacker.example"})
    assert res.status_code == 400
    assert res.headers["x-content-type-options"] == "nosniff"


def test_headers_on_frontend_proxy_response(client):
    res = client.get("/index.html")  # proxied; upstream is down in tests -> 502, still headered
    assert res.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in res.headers["content-security-policy"]


def test_asset_get_is_inert_and_not_overridden_by_middleware(client):
    sleeve = _post(client, "image/png", GOOD["image/png"]).json()["sleeve_id"]
    res = client.get(f"/api/me/sleeves/{sleeve}/image")
    assert res.headers["content-type"] == "image/png"
    assert res.headers["content-security-policy"] == ASSET_CSP
    for name, value in EXPECTED_STATIC.items():
        assert res.headers[name] == value
    assert len(res.headers.get_list("content-security-policy")) == 1


def test_csp_value_is_pinned():
    assert csp_for("localhost:8000") == (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob: https://cards.scryfall.io; media-src 'self' blob:; "
        "connect-src 'self' ws://localhost:8000 wss://localhost:8000; "
        "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
    )
    assert "unsafe-eval" not in csp_for(None)
    assert "script-src 'self';" in csp_for(None)


def test_csp_never_interpolates_a_hostile_authority():
    assert "evil" not in csp_for("x; script-src evil.example")
    assert "ws://" not in csp_for("a b")


def test_frontend_dev_csp_allows_loopback_api():
    assert "http://localhost:*" in csp_for(None, frontend_dev=True)
    assert "http://localhost:*" not in csp_for(None)


def test_static_header_set_is_complete():
    assert {k.lower(): v for k, v in STATIC_SECURITY_HEADERS} == EXPECTED_STATIC
