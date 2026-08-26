"""Tests for ArchidektClient (services/archidekt_client.py) and
GET /api/import/archidekt/{deck_id}.

Reference: docs/implementation-state/Done_Backend.md "Import — follow-up from the frontend".
"""

import httpx2 as httpx
import pytest
from fastapi.testclient import TestClient

from mtg_analyzer.api.app import app
from mtg_analyzer.api.dependencies import get_archidekt_client
from mtg_analyzer.services.archidekt_client import ArchidektClient, ArchidektFetchError, extract_deck_id

DECK_BODY = {
    "name": "Krenko Goblins",
    "categories": [
        {"name": "Commander", "includedInDeck": True},
        {"name": "Maybeboard", "includedInDeck": False},
    ],
    "cards": [
        {"quantity": 1, "categories": ["Commander"], "card": {"oracleCard": {"name": "Krenko, Mob Boss"}}},
        {"quantity": 1, "categories": [], "card": {"oracleCard": {"name": "Sol Ring"}}},
        {"quantity": 30, "categories": None, "card": {"oracleCard": {"name": "Mountain"}}},
        {"quantity": 1, "categories": ["Sideboard"], "card": {"oracleCard": {"name": "Negate"}}},
        {"quantity": 1, "categories": ["Maybeboard"], "card": {"oracleCard": {"name": "Not Actually In Deck"}}},
    ],
}


def make_client(handler) -> ArchidektClient:
    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, base_url="https://archidekt.com")
    return ArchidektClient(client=client)


class TestExtractDeckId:
    def test_bare_id_passes_through(self):
        assert extract_deck_id("12345") == "12345"

    def test_full_url(self):
        assert extract_deck_id("https://archidekt.com/decks/12345/krenko-goblins") == "12345"

    def test_full_url_with_trailing_slash(self):
        assert extract_deck_id("https://archidekt.com/decks/12345/") == "12345"

    def test_strips_whitespace(self):
        assert extract_deck_id("  12345  ") == "12345"


class TestArchidektClientFetchDecklist:
    def test_success_converts_cards_to_decklist_text_by_category(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/decks/12345/"
            assert request.url.params["format"] == "json"
            return httpx.Response(200, json=DECK_BODY)

        client = make_client(handler)
        result = client.fetch_decklist("12345")

        assert result["name"] == "Krenko Goblins"
        assert result["commanderText"] == "1 Krenko, Mob Boss"
        mainboard_lines = result["mainboardText"].splitlines()
        assert "1 Sol Ring" in mainboard_lines
        assert "30 Mountain" in mainboard_lines
        assert result["sideboardText"] == "1 Negate"

    def test_excludes_categories_not_included_in_deck(self):
        # Maybeboard is flagged includedInDeck=False at the deck level —
        # its card must not show up in any of the three sections.
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=DECK_BODY)

        client = make_client(handler)
        result = client.fetch_decklist("12345")

        combined = result["commanderText"] + result["mainboardText"] + result["sideboardText"]
        assert "Not Actually In Deck" not in combined

    def test_accepts_full_url_as_deck_id(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/decks/12345/"
            return httpx.Response(200, json=DECK_BODY)

        client = make_client(handler)
        result = client.fetch_decklist("https://archidekt.com/decks/12345/krenko-goblins")

        assert result["name"] == "Krenko Goblins"

    def test_non_numeric_id_raises_400_without_a_request(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("should not make a request for a non-numeric id")

        client = make_client(handler)
        with pytest.raises(ArchidektFetchError) as exc_info:
            client.fetch_decklist("not-a-number")
        assert exc_info.value.status == 400

    def test_404_raises_with_status(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"error": "Deck not found."})

        client = make_client(handler)
        with pytest.raises(ArchidektFetchError) as exc_info:
            client.fetch_decklist("999999999")
        assert exc_info.value.status == 404

    def test_other_error_status_raises(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="server error")

        client = make_client(handler)
        with pytest.raises(ArchidektFetchError) as exc_info:
            client.fetch_decklist("12345")
        assert exc_info.value.status == 500

    def test_body_without_cards_raises(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"unexpected": "shape"})

        client = make_client(handler)
        with pytest.raises(ArchidektFetchError):
            client.fetch_decklist("12345")


class TestImportArchidektEndpoint:
    def teardown_method(self):
        app.dependency_overrides.pop(get_archidekt_client, None)

    def test_success(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=DECK_BODY)

        app.dependency_overrides[get_archidekt_client] = lambda: make_client(handler)
        client = TestClient(app)

        response = client.get("/api/import/archidekt/12345")

        assert response.status_code == 200
        body = response.json()
        assert body["name"] == "Krenko Goblins"
        assert body["commanderText"] == "1 Krenko, Mob Boss"

    def test_404_from_archidekt_becomes_404(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"error": "Deck not found."})

        app.dependency_overrides[get_archidekt_client] = lambda: make_client(handler)
        client = TestClient(app)

        response = client.get("/api/import/archidekt/999999999")

        assert response.status_code == 404

    def test_non_numeric_id_becomes_400(self):
        app.dependency_overrides[get_archidekt_client] = lambda: make_client(
            lambda request: httpx.Response(200, json=DECK_BODY)
        )
        client = TestClient(app)

        response = client.get("/api/import/archidekt/not-a-number")

        assert response.status_code == 400

    def test_unexpected_error_becomes_502(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="server error")

        app.dependency_overrides[get_archidekt_client] = lambda: make_client(handler)
        client = TestClient(app)

        response = client.get("/api/import/archidekt/12345")

        assert response.status_code == 502

    def test_full_url_with_percent_encoded_slashes_is_routed_correctly(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=DECK_BODY)

        app.dependency_overrides[get_archidekt_client] = lambda: make_client(handler)
        client = TestClient(app)

        response = client.get(
            "/api/import/archidekt/https:%2F%2Farchidekt.com%2Fdecks%2F12345%2Fkrenko-goblins"
        )

        assert response.status_code == 200
        assert response.json()["name"] == "Krenko Goblins"
