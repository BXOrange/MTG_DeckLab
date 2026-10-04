"""API tests for lazy combo loading and explicit local-data refresh controls."""

import gzip
import json
from types import SimpleNamespace

import httpx2 as httpx
from fastapi.testclient import TestClient

from mtg_analyzer.api.app import app
from mtg_analyzer.api.cards import get_card_database
from mtg_analyzer.api.dependencies import get_commander_spellbook_database
from mtg_analyzer.services import commander_spellbook_database as spellbook
from mtg_analyzer.services.card_database import CardDatabase
from mtg_analyzer.services.commander_spellbook_database import CommanderSpellbookDatabase


def _snapshot_bytes():
    payload = {
        "timestamp": "2025-01-01",
        "version": "1.0",
        "aliases": [],
        "variants": [
            {
                "id": "combo-1",
                "status": "OK",
                "uses": [
                    {"card": {"name": "Alpha"}, "quantity": 1},
                    {"card": {"name": "Beta"}, "quantity": 1},
                ],
                "requires": [],
                "produces": [
                    {"feature": {"name": "Infinite mana"}, "quantity": 1}
                ],
            }
        ],
    }
    return gzip.compress(json.dumps(payload).encode())


class TestComboRoutes:
    def teardown_method(self):
        app.dependency_overrides.pop(get_commander_spellbook_database, None)

    def test_status_is_read_only_and_matches_initialize_on_first_use(
        self, tmp_path, monkeypatch
    ):
        database = CommanderSpellbookDatabase(tmp_path / "spellbook.sqlite")
        app.dependency_overrides[get_commander_spellbook_database] = lambda: database
        snapshot = gzip.decompress(_snapshot_bytes())
        requests = []
        client_type = httpx.Client

        def handler(request):
            requests.append(request)
            return httpx.Response(200, content=snapshot)

        monkeypatch.setattr(
            spellbook.httpx,
            "Client",
            lambda **kwargs: client_type(transport=httpx.MockTransport(handler), **kwargs),
        )
        client = TestClient(app)

        status = client.get("/api/combos/status")
        matches = client.post(
            "/api/combos/matches",
            json={"cards": [{"name": "Alpha", "quantity": 1}, {"name": "Beta"}]},
        )

        assert status.status_code == 200
        assert status.json()["initialized"] is False
        assert len(requests) == 1
        assert matches.status_code == 200
        body = matches.json()
        assert body["combos"][0]["id"] == "combo-1"
        assert body["combos"][0]["producesInfinite"] is True
        assert body["database"]["initialized"] is True


class TestCardPoolUpdateRoute:
    def teardown_method(self):
        app.dependency_overrides.pop(get_card_database, None)

    def test_successful_update_reports_current_cached_card_count(self, monkeypatch):
        database = CardDatabase()
        app.dependency_overrides[get_card_database] = lambda: database
        monkeypatch.setattr(
            "mtg_analyzer.api.cards.subprocess.run",
            lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="updated", stderr=""),
        )

        response = TestClient(app).post("/api/cards/update")

        assert response.status_code == 200
        assert response.json() == {"updated": True, "cachedCardCount": 0}

    def test_failed_update_is_reported_as_server_error(self, monkeypatch):
        monkeypatch.setattr(
            "mtg_analyzer.api.cards.subprocess.run",
            lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="", stderr="failure"),
        )

        response = TestClient(app).post("/api/cards/update")

        assert response.status_code == 502
        assert "update failed" in response.json()["detail"].lower()
