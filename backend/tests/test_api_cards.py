"""Tests for GET /api/cards, GET /api/cards/search, POST /api/cards/resolve.

Reference: docs/implementation-state/Done_Backend.md "HTTP API foundation".
"""

import httpx2 as httpx
from fastapi.testclient import TestClient

from mtg_analyzer.api.app import app
from mtg_analyzer.api.cards import get_lazy_card_loader
from mtg_analyzer.api.dependencies import get_card_database
from mtg_analyzer.services.card_database import CardDatabase
from mtg_analyzer.services.lazy_card_loader import LazyCardLoader
from mtg_analyzer.services.scryfall_client import ScryfallIntegration

LIGHTNING_BOLT = {
    "id": "77c17415-56c9-4677-b6d5-e18641640e6f",
    "name": "Lightning Bolt",
    "mana_cost": "{R}",
    "cmc": 1.0,
    "type_line": "Instant",
    "oracle_text": "Lightning Bolt deals 3 damage to any target.",
    "colors": ["R"],
    "color_identity": ["R"],
    "keywords": [],
    "set": "clu",
    "rarity": "common",
    "image_uris": {"small": "", "normal": "", "large": "", "png": ""},
}


def _override_loader(handler):
    database = CardDatabase()
    transport = httpx.MockTransport(handler)
    scryfall = ScryfallIntegration(client=httpx.Client(transport=transport, base_url="https://api.scryfall.com"))
    loader = LazyCardLoader(database, scryfall)
    app.dependency_overrides[get_lazy_card_loader] = lambda: loader
    app.dependency_overrides[get_card_database] = lambda: database
    return loader, database


class TestSearchCard:
    def teardown_method(self):
        app.dependency_overrides.pop(get_lazy_card_loader, None)
        app.dependency_overrides.pop(get_card_database, None)

    def test_found_card_returns_card_dict(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": [LIGHTNING_BOLT], "not_found": []})

        _override_loader(handler)
        client = TestClient(app)

        response = client.get("/api/cards/search", params={"name": "Lightning Bolt"})

        assert response.status_code == 200
        body = response.json()
        assert body["name"] == "Lightning Bolt"
        assert body["is_instant"] is True

    def test_unknown_card_returns_404(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/cards/collection":
                return httpx.Response(
                    200, json={"data": [], "not_found": [{"name": "Not A Real Card"}]}
                )
            # The flavor-name fallback retry (LazyCardLoader.load_cards)
            # hits /cards/named for a collection miss — genuinely unknown here too.
            return httpx.Response(404, json={"details": "not found"})

        _override_loader(handler)
        client = TestClient(app)

        response = client.get("/api/cards/search", params={"name": "Not A Real Card"})

        assert response.status_code == 404

    def test_missing_name_param_is_422(self):
        client = TestClient(app)
        response = client.get("/api/cards/search")
        assert response.status_code == 422


class TestListCards:
    def teardown_method(self):
        app.dependency_overrides.pop(get_lazy_card_loader, None)
        app.dependency_overrides.pop(get_card_database, None)

    def test_empty_cache_returns_empty_list(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("must not call Scryfall for a plain cache listing")

        _override_loader(handler)
        client = TestClient(app)

        response = client.get("/api/cards")

        assert response.status_code == 200
        assert response.json() == []

    def test_lists_previously_resolved_cards(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": [LIGHTNING_BOLT], "not_found": []})

        loader, _ = _override_loader(handler)
        loader.load_cards(["Lightning Bolt"])
        client = TestClient(app)

        response = client.get("/api/cards")

        assert response.status_code == 200
        body = response.json()
        assert len(body) == 1
        assert body[0]["name"] == "Lightning Bolt"


class TestResolveCards:
    def teardown_method(self):
        app.dependency_overrides.pop(get_lazy_card_loader, None)
        app.dependency_overrides.pop(get_card_database, None)

    def test_resolves_multiple_names_in_one_call(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/cards/collection":
                return httpx.Response(
                    200, json={"data": [LIGHTNING_BOLT], "not_found": [{"name": "Not A Real Card"}]}
                )
            # The flavor-name fallback retry (LazyCardLoader.load_cards)
            # hits /cards/named for a collection miss — genuinely unknown here too.
            return httpx.Response(404, json={"details": "not found"})

        _override_loader(handler)
        client = TestClient(app)

        response = client.post(
            "/api/cards/resolve", json={"names": ["Lightning Bolt", "Not A Real Card"]}
        )

        assert response.status_code == 200
        body = response.json()
        assert body["cards"]["Lightning Bolt"]["name"] == "Lightning Bolt"
        assert body["notFound"] == ["Not A Real Card"]

    def test_empty_names_returns_empty_result(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("must not call Scryfall for an empty request")

        _override_loader(handler)
        client = TestClient(app)

        response = client.post("/api/cards/resolve", json={"names": []})

        assert response.status_code == 200
        assert response.json() == {"cards": {}, "notFound": []}
