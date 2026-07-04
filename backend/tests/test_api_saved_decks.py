"""Tests for POST /api/decks/save, GET /api/decks, GET/DELETE /api/decks/{id}.

Reference: backend/TODO.md "Deck persistence".
"""

from fastapi.testclient import TestClient

from mtg_analyzer.api.app import app
from mtg_analyzer.api.dependencies import get_deck_database
from mtg_analyzer.services.deck_database import DeckDatabase


def _override_database() -> DeckDatabase:
    database = DeckDatabase()
    app.dependency_overrides[get_deck_database] = lambda: database
    return database


class TestSaveDeck:
    def teardown_method(self):
        app.dependency_overrides.pop(get_deck_database, None)

    def test_save_without_id_creates_a_new_deck(self):
        _override_database()
        client = TestClient(app)

        response = client.post(
            "/api/decks/save",
            json={"name": "Goblins", "commanderText": "1 Krenko, Mob Boss\n"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["name"] == "Goblins"
        assert body["commanderText"] == "1 Krenko, Mob Boss\n"
        assert body["id"]
        assert body["analysisId"] is None

    def test_saving_twice_without_id_creates_two_decks(self):
        database = _override_database()
        client = TestClient(app)

        client.post("/api/decks/save", json={"name": "Goblins"})
        client.post("/api/decks/save", json={"name": "Goblins"})

        assert len(database.list_decks()) == 2

    def test_save_with_existing_id_updates_in_place(self):
        database = _override_database()
        client = TestClient(app)

        created = client.post("/api/decks/save", json={"name": "Goblins"}).json()

        updated = client.post(
            "/api/decks/save",
            json={"id": created["id"], "name": "Goblins v2", "mainboardText": "1 Sol Ring\n"},
        ).json()

        assert updated["id"] == created["id"]
        assert updated["name"] == "Goblins v2"
        assert updated["createdAt"] == created["createdAt"]
        assert len(database.list_decks()) == 1

    def test_update_preserves_analysis_id(self):
        database = _override_database()
        client = TestClient(app)

        created = client.post("/api/decks/save", json={"name": "Goblins"}).json()
        deck = database.get_deck(created["id"])
        deck.analysis_id = "analysis-123"
        database.save_deck(deck)

        updated = client.post(
            "/api/decks/save", json={"id": created["id"], "name": "Goblins v2"}
        ).json()

        assert updated["analysisId"] == "analysis-123"


class TestListDecks:
    def teardown_method(self):
        app.dependency_overrides.pop(get_deck_database, None)

    def test_empty_database_returns_empty_list(self):
        _override_database()
        client = TestClient(app)
        response = client.get("/api/decks")
        assert response.status_code == 200
        assert response.json() == []

    def test_lists_saved_decks(self):
        _override_database()
        client = TestClient(app)
        client.post("/api/decks/save", json={"name": "Goblins"})
        client.post("/api/decks/save", json={"name": "Elves"})

        response = client.get("/api/decks")

        assert response.status_code == 200
        names = {deck["name"] for deck in response.json()}
        assert names == {"Goblins", "Elves"}


class TestGetDeck:
    def teardown_method(self):
        app.dependency_overrides.pop(get_deck_database, None)

    def test_get_existing_deck(self):
        _override_database()
        client = TestClient(app)
        created = client.post("/api/decks/save", json={"name": "Goblins"}).json()

        response = client.get(f"/api/decks/{created['id']}")

        assert response.status_code == 200
        assert response.json()["name"] == "Goblins"

    def test_get_missing_deck_returns_404(self):
        _override_database()
        client = TestClient(app)
        response = client.get("/api/decks/nonexistent-id")
        assert response.status_code == 404


class TestDeleteDeck:
    def teardown_method(self):
        app.dependency_overrides.pop(get_deck_database, None)

    def test_delete_existing_deck(self):
        database = _override_database()
        client = TestClient(app)
        created = client.post("/api/decks/save", json={"name": "Goblins"}).json()

        response = client.delete(f"/api/decks/{created['id']}")

        assert response.status_code == 200
        assert response.json() == {"deleted": True}
        assert database.get_deck(created["id"]) is None

    def test_delete_missing_deck_returns_404(self):
        _override_database()
        client = TestClient(app)
        response = client.delete("/api/decks/nonexistent-id")
        assert response.status_code == 404
