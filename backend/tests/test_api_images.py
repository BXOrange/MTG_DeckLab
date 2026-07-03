"""Tests for GET /api/cards/{card_id}/image.

Reference: docs/06_CARD_GRAPHICS_AND_LAZY_LOADING.md,
docs/08_CARD_CACHE_EXPORT_IMPORT.md.
"""

import httpx2 as httpx
from fastapi.testclient import TestClient

from mtg_analyzer.api.app import app
from mtg_analyzer.api.dependencies import get_card_database, get_image_cache
from mtg_analyzer.models.card import Card
from mtg_analyzer.services.card_database import CardDatabase
from mtg_analyzer.services.image_cache import ImageCache

CARD_ID = "77c17415-56c9-4677-b6d5-e18641640e6f"


def _seed_database() -> CardDatabase:
    database = CardDatabase()
    database.save_card(
        Card(
            id=CARD_ID,
            name="Lightning Bolt",
            type_line="Instant",
            is_instant=True,
            image_uri_normal="https://cards.scryfall.io/normal/lightning_bolt.jpg",
        )
    )
    return database


def _override(tmp_path, handler):
    database = _seed_database()
    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, base_url="https://cards.scryfall.io")
    images = ImageCache(cache_dir=tmp_path / "images", client=client)
    app.dependency_overrides[get_card_database] = lambda: database
    app.dependency_overrides[get_image_cache] = lambda: images


class TestGetCardImage:
    def teardown_method(self):
        app.dependency_overrides.pop(get_card_database, None)
        app.dependency_overrides.pop(get_image_cache, None)

    def test_downloads_and_returns_image_bytes(self, tmp_path):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"fake-image-bytes")

        _override(tmp_path, handler)
        client = TestClient(app)

        response = client.get(f"/api/cards/{CARD_ID}/image")

        assert response.status_code == 200
        assert response.content == b"fake-image-bytes"

    def test_unknown_card_returns_404(self, tmp_path):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"fake-image-bytes")

        _override(tmp_path, handler)
        client = TestClient(app)

        response = client.get("/api/cards/not-a-real-id/image")

        assert response.status_code == 404

    def test_invalid_size_returns_400(self, tmp_path):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"fake-image-bytes")

        _override(tmp_path, handler)
        client = TestClient(app)

        response = client.get(f"/api/cards/{CARD_ID}/image", params={"size": "huge"})

        assert response.status_code == 400

    def test_missing_size_variant_returns_404(self, tmp_path):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"fake-image-bytes")

        _override(tmp_path, handler)
        client = TestClient(app)

        response = client.get(f"/api/cards/{CARD_ID}/image", params={"size": "large"})

        assert response.status_code == 404
