"""VIS-24: one error shape, localized by the caller's language, no user-facing literal in `api/`."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from mtg_analyzer.api.errors import install_error_handlers
from mtg_analyzer.i18n import api_error, error_from, LocalizedError

API_DIR = Path(__file__).resolve().parents[2] / "mtg_analyzer" / "api"

#: `HTTPException` calls allowed to carry no ``detail`` code (no user text at all).
BODYLESS_ALLOWLIST = {("console_status.py", 404)}


def _client() -> TestClient:
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/coded/{deck_id}")
    def coded(deck_id: str):
        raise api_error(404, "deck_not_found", deck_id=deck_id, headers={"Retry-After": "3"})

    @app.get("/legacy")
    def legacy():
        raise HTTPException(403, {"code": "csrf"})

    @app.get("/plain")
    def plain():
        raise HTTPException(418, "short and stout")

    @app.get("/service")
    def service():
        raise error_from(LocalizedError("lobby_full"), 400)

    @app.get("/engine")
    def engine():
        raise error_from(ValueError("no mana left"), 400)

    return TestClient(app)


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        ({}, 'Kein gespeichertes Deck mit der ID "d1".'),
        ({"Cookie": "mtg_lang=en"}, 'No saved deck with id "d1".'),
        ({"Accept-Language": "en-US,en;q=0.9,de;q=0.4"}, 'No saved deck with id "d1".'),
        ({"Accept-Language": "fr-FR,fr;q=0.9"}, 'Kein gespeichertes Deck mit der ID "d1".'),
        ({"Cookie": "mtg_lang=de", "Accept-Language": "en"}, 'Kein gespeichertes Deck mit der ID "d1".'),
        ({"Cookie": "mtg_lang=xx", "Accept-Language": "en"}, 'No saved deck with id "d1".'),  # junk cookie ignored
    ],
)
def test_api_error_carries_code_params_and_localized_message(headers, expected):
    response = _client().get("/coded/d1", headers=headers)
    assert response.status_code == 404
    assert response.headers["Retry-After"] == "3"  # headers survive the handler
    assert response.json() == {"detail": {"code": "deck_not_found", "deck_id": "d1", "message": expected}}


def test_existing_code_only_bodies_gain_a_message_with_the_same_code():
    client = _client()
    german = client.get("/legacy").json()["detail"]
    english = client.get("/legacy", headers={"Cookie": "mtg_lang=en"}).json()["detail"]
    assert german["code"] == english["code"] == "csrf"
    assert german["message"] != english["message"]


def test_plain_framework_strings_are_left_alone():
    assert _client().get("/plain").json() == {"detail": "short and stout"}


def test_service_errors_translate_at_the_boundary_and_engine_text_passes_through():
    client = _client()
    assert client.get("/service", headers={"Cookie": "mtg_lang=en"}).json()["detail"] == {
        "code": "lobby_full",
        "message": "The lobby is full - please try again later.",
    }
    assert client.get("/engine").json()["detail"] == {"code": "action_rejected", "message": "no mana left"}


def test_no_http_exception_in_api_carries_a_plain_string_detail():
    """Every user-facing refusal goes through `api_error` / `error_from` or a `{"code": ...}` body."""
    offenders: list[str] = []
    for path in sorted(API_DIR.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "HTTPException"):
                continue
            detail = node.args[1] if len(node.args) > 1 else next(
                (kw.value for kw in node.keywords if kw.arg == "detail"), None
            )
            if detail is None:
                status = node.args[0] if node.args else next(
                    (kw.value for kw in node.keywords if kw.arg == "status_code"), None
                )
                if (path.name, getattr(status, "value", None)) in BODYLESS_ALLOWLIST:
                    continue
            elif not isinstance(detail, (ast.Constant, ast.JoinedStr)) or (
                isinstance(detail, ast.Constant) and not isinstance(detail.value, str)
            ):
                continue
            offenders.append(f"{path.name}:{node.lineno}")
    assert not offenders, f"plain-text HTTPException details left: {offenders}"
