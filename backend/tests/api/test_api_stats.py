"""Tests for the lightweight home-page aggregate counts."""

from fastapi.testclient import TestClient

from mtg_analyzer.api.app import app
from mtg_analyzer.api.dependencies import get_card_database, get_deck_database, get_lobby
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.decks.deck import Deck
from mtg_analyzer.services.card_database import CardDatabase
from mtg_analyzer.services.deck_database import DeckDatabase
from mtg_analyzer.services.lobby import Lobby


def test_stats_count_cached_cards_saved_decks_and_connected_humans():
    cards = CardDatabase()
    cards.save_card(Card(id="forest", name="Forest", type_line="Basic Land — Forest"))
    decks = DeckDatabase()
    decks.save_deck(Deck(name="Test deck"))
    lobby = Lobby()
    connected = lobby.connect("Connected")
    disconnected = lobby.connect("Disconnected")
    lobby.disconnect(disconnected.id)
    app.dependency_overrides[get_card_database] = lambda: cards
    app.dependency_overrides[get_deck_database] = lambda: decks
    app.dependency_overrides[get_lobby] = lambda: lobby

    try:
        response = TestClient(app).get("/api/stats")
    finally:
        app.dependency_overrides.pop(get_card_database, None)
        app.dependency_overrides.pop(get_deck_database, None)
        app.dependency_overrides.pop(get_lobby, None)
        cards.close()
        decks.close()

    assert response.status_code == 200
    assert response.json() == {"cards": 1, "decks": 1, "players": 1}
    assert lobby.player(connected.id).connected
