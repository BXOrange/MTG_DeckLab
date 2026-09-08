"""Tests for GET /api/archetypes and POST /api/archetypes/analyze.

Reference: mtg_analyzer/api/archetypes.py, services/archetype_analysis.py.
"""

from fastapi.testclient import TestClient

from mtg_analyzer.api.app import app
from mtg_analyzer.api.dependencies import get_deck_database, get_lazy_card_loader
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.services.deck_database import DeckDatabase
from mtg_analyzer.services.lazy_card_loader import LoadCardsResult


def _override_database() -> DeckDatabase:
    database = DeckDatabase()
    app.dependency_overrides[get_deck_database] = lambda: database
    return database


class _FakeLoader:
    def __init__(self, cards):
        self._cards = cards

    def load_cards(self, names):
        return LoadCardsResult(
            cards={n: self._cards[n] for n in names if n in self._cards},
            not_found=[n for n in names if n not in self._cards],
        )


def _override_loader(cards):
    app.dependency_overrides[get_lazy_card_loader] = lambda: _FakeLoader(cards)


def _blood_artist():
    return Card(
        id="blood-artist",
        name="Blood Artist",
        type_line="Creature — Vampire",
        is_creature=True,
        power=0,
        toughness=1,
        oracle_text="Whenever Blood Artist or another creature dies, target player loses 1 life and you gain 1 life.",
    )


class TestListArchetypes:
    def teardown_method(self):
        app.dependency_overrides.pop(get_deck_database, None)
        app.dependency_overrides.pop(get_lazy_card_loader, None)

    def test_returns_the_full_catalogue(self):
        client = TestClient(app)
        res = client.get("/api/archetypes")
        assert res.status_code == 200
        data = res.json()
        assert len(data) > 0
        assert any(entry["id"] == "aristocrats" for entry in data)


class TestAnalyzeArchetypes:
    def teardown_method(self):
        app.dependency_overrides.pop(get_deck_database, None)
        app.dependency_overrides.pop(get_lazy_card_loader, None)

    def test_analyze_from_raw_text(self):
        _override_loader({"Blood Artist": _blood_artist()})
        client = TestClient(app)

        res = client.post(
            "/api/archetypes/analyze",
            json={"mainboardText": "4 Blood Artist\n"},
        )

        assert res.status_code == 200
        data = res.json()
        assert "suggestions" in data and "typalSignals" in data
        assert any(s["id"] == "aristocrats" for s in data["suggestions"])

    def test_analyze_from_saved_deck_id(self):
        database = _override_database()
        _override_loader({"Blood Artist": _blood_artist()})
        client = TestClient(app)

        saved = client.post(
            "/api/decks/save", json={"name": "Sac Deck", "mainboardText": "4 Blood Artist\n"}
        ).json()

        res = client.post("/api/archetypes/analyze", json={"deckId": saved["id"]})

        assert res.status_code == 200
        assert any(s["id"] == "aristocrats" for s in res.json()["suggestions"])

    def test_analyze_unknown_deck_id_404s(self):
        _override_database()
        _override_loader({})
        client = TestClient(app)

        res = client.post("/api/archetypes/analyze", json={"deckId": "not-a-real-id"})

        assert res.status_code == 404
