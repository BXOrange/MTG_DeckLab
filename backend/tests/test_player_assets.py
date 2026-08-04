"""Tests for per-player favorite decks (`services/player_assets.py`,
`api/player_assets.py`).

Reference: docs/implementation-state/Done_Backend.md "PLR-13" — favorite
decks are read by goldfishView.js/multiplayerView.js to list starred decks
first in the deck picker.
"""

from fastapi.testclient import TestClient

from mtg_analyzer.api.app import app
from mtg_analyzer.api.dependencies import get_player_asset_store
from mtg_analyzer.services.player_assets import PlayerAssetStore


def _setup():
    store = PlayerAssetStore(":memory:")
    app.dependency_overrides[get_player_asset_store] = lambda: store
    return store


def _teardown():
    app.dependency_overrides.pop(get_player_asset_store, None)


class TestPlayerAssetStoreFavoriteDecks:
    def test_starts_empty(self):
        store = PlayerAssetStore(":memory:")
        assert store.list_favorite_decks("Alex") == []

    def test_add_then_list(self):
        store = PlayerAssetStore(":memory:")
        store.add_favorite_deck("Alex", "deck-1")
        assert store.list_favorite_decks("Alex") == ["deck-1"]

    def test_adding_twice_does_not_duplicate(self):
        store = PlayerAssetStore(":memory:")
        store.add_favorite_deck("Alex", "deck-1")
        store.add_favorite_deck("Alex", "deck-1")
        assert store.list_favorite_decks("Alex") == ["deck-1"]

    def test_remove(self):
        store = PlayerAssetStore(":memory:")
        store.add_favorite_deck("Alex", "deck-1")
        assert store.remove_favorite_deck("Alex", "deck-1") is True
        assert store.list_favorite_decks("Alex") == []

    def test_removing_absent_favorite_is_a_no_op(self):
        store = PlayerAssetStore(":memory:")
        assert store.remove_favorite_deck("Alex", "nope") is False

    def test_scoped_per_player(self):
        store = PlayerAssetStore(":memory:")
        store.add_favorite_deck("Alex", "deck-1")
        assert store.list_favorite_decks("Sam") == []


class TestFavoriteDecksApi:
    def teardown_method(self):
        _teardown()

    def test_round_trip(self):
        _setup()
        client = TestClient(app)
        assert client.get("/api/players/Alex/favorite-decks").json() == []

        response = client.post("/api/players/Alex/favorite-decks", json={"deckId": "deck-1"})
        assert response.status_code == 200
        assert response.json() == {"deck_id": "deck-1"}
        assert client.get("/api/players/Alex/favorite-decks").json() == ["deck-1"]

        response = client.delete("/api/players/Alex/favorite-decks/deck-1")
        assert response.status_code == 200
        assert client.get("/api/players/Alex/favorite-decks").json() == []

    def test_empty_deck_id_is_rejected(self):
        _setup()
        client = TestClient(app)
        response = client.post("/api/players/Alex/favorite-decks", json={"deckId": "  "})
        assert response.status_code == 400
