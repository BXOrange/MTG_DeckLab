"""Tests for the HTTP API (POST /api/decks, GET /api/health).

Reference: backend/ToDo_Backend.md "HTTP API foundation".
"""

import httpx2 as httpx
from fastapi.testclient import TestClient

from mtg_analyzer.api.app import app
from mtg_analyzer.api.decks import get_lazy_card_loader
from mtg_analyzer.services.card_database import CardDatabase
from mtg_analyzer.services.lazy_card_loader import LazyCardLoader
from mtg_analyzer.services.scryfall_client import ScryfallIntegration

client = TestClient(app)

SAMPLE_MAINBOARD = "\n".join(f"1 Goblin {i}" for i in range(37)) + "\n62 Mountain\n"

KRENKO = {
    "id": "11111111-1111-1111-1111-111111111111",
    "name": "Krenko, Mob Boss",
    "mana_cost": "{2}{R}{R}",
    "cmc": 4.0,
    "type_line": "Legendary Creature — Goblin",
    "oracle_text": "",
    "power": "3",
    "toughness": "3",
    "colors": ["R"],
    "color_identity": ["R"],
    "keywords": [],
    "set": "cma",
    "rarity": "rare",
    "image_uris": {"small": "", "normal": "", "large": "", "png": ""},
}

CULTIVATE = {
    "id": "22222222-2222-2222-2222-222222222222",
    "name": "Cultivate",
    "mana_cost": "{2}{G}",
    "cmc": 3.0,
    "type_line": "Sorcery",
    "oracle_text": "Search your library for up to two basic land cards...",
    "colors": ["G"],
    "color_identity": ["G"],
    "keywords": [],
    "set": "cma",
    "rarity": "common",
    "image_uris": {"small": "", "normal": "", "large": "", "png": ""},
}


def _not_found_handler(request: httpx.Request) -> httpx.Response:
    import json

    identifiers = json.loads(request.read())["identifiers"]
    return httpx.Response(
        200,
        json={"data": [], "not_found": [{"name": i["name"]} for i in identifiers]},
    )


def _override_loader(handler):
    database = CardDatabase()
    transport = httpx.MockTransport(handler)
    scryfall = ScryfallIntegration(
        client=httpx.Client(transport=transport, base_url="https://api.scryfall.com")
    )
    loader = LazyCardLoader(database, scryfall)
    app.dependency_overrides[get_lazy_card_loader] = lambda: loader
    return loader


class TestHealth:
    def test_health_ok(self):
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestSubmitDeck:
    def teardown_method(self):
        app.dependency_overrides.pop(get_lazy_card_loader, None)

    def test_legal_deck_round_trip(self):
        _override_loader(_not_found_handler)
        response = client.post(
            "/api/decks",
            json={
                "commanderText": "1 Krenko, Mob Boss",
                "mainboardText": SAMPLE_MAINBOARD,
                "sideboardText": "",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["totalCount"] == 100
        assert body["validation"]["isLegal"] is True
        assert body["commanders"] == [{"name": "Krenko, Mob Boss", "qty": 1}]

    def test_illegal_deck_reports_errors(self):
        _override_loader(_not_found_handler)
        response = client.post("/api/decks", json={"mainboardText": "1 Sol Ring"})
        assert response.status_code == 200
        body = response.json()
        assert body["validation"]["isLegal"] is False
        assert body["validation"]["errors"]

    def test_missing_fields_default_to_empty(self):
        _override_loader(_not_found_handler)
        response = client.post("/api/decks", json={})
        assert response.status_code == 200
        body = response.json()
        assert body["totalCount"] == 0
        assert body["validation"]["warnings"]

    def test_snake_case_field_names_also_accepted(self):
        _override_loader(_not_found_handler)
        response = client.post("/api/decks", json={"mainboard_text": "1 Sol Ring"})
        assert response.status_code == 200
        assert response.json()["totalCount"] == 1

    def test_card_outside_commander_color_identity_is_reported(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": [KRENKO, CULTIVATE], "not_found": []})

        _override_loader(handler)
        response = client.post(
            "/api/decks",
            json={"commanderText": "1 Krenko, Mob Boss", "mainboardText": "1 Cultivate"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["validation"]["isLegal"] is False
        assert any("Cultivate" in error for error in body["validation"]["errors"])

    def test_unresolved_cards_add_a_warning_but_no_error(self):
        _override_loader(_not_found_handler)
        response = client.post(
            "/api/decks",
            json={"commanderText": "1 Not A Real Commander", "mainboardText": "1 Sol Ring"},
        )

        assert response.status_code == 200
        body = response.json()
        assert any("Not A Real Commander" in warning for warning in body["validation"]["warnings"])
