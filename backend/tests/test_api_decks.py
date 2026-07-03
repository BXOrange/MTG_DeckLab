"""Tests for the HTTP API (POST /api/decks, GET /api/health).

Reference: backend/TODO.md "HTTP API foundation".
"""

from fastapi.testclient import TestClient

from mtg_analyzer.api.app import app

client = TestClient(app)

SAMPLE_MAINBOARD = "\n".join(f"1 Goblin {i}" for i in range(37)) + "\n62 Mountain\n"


class TestHealth:
    def test_health_ok(self):
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestSubmitDeck:
    def test_legal_deck_round_trip(self):
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
        response = client.post("/api/decks", json={"mainboardText": "1 Sol Ring"})
        assert response.status_code == 200
        body = response.json()
        assert body["validation"]["isLegal"] is False
        assert body["validation"]["errors"]

    def test_missing_fields_default_to_empty(self):
        response = client.post("/api/decks", json={})
        assert response.status_code == 200
        body = response.json()
        assert body["totalCount"] == 0
        assert body["validation"]["warnings"]

    def test_snake_case_field_names_also_accepted(self):
        response = client.post("/api/decks", json={"mainboard_text": "1 Sol Ring"})
        assert response.status_code == 200
        assert response.json()["totalCount"] == 1
