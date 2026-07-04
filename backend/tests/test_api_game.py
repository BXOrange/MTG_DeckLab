"""Tests for the game session HTTP API (goldfish, action, rewind, restart).

Reference: mtg_analyzer/api/game.py, docs/02_MVP_USECASES_REVISED.md UC3/UC4.
"""

from fastapi.testclient import TestClient

from mtg_analyzer.api.app import app
from mtg_analyzer.api.dependencies import (
    get_deck_database,
    get_game_session_manager,
    get_lazy_card_loader,
)
from mtg_analyzer.models.card import Card
from mtg_analyzer.services.deck_database import DeckDatabase
from mtg_analyzer.services.game_session import GameSessionManager
from mtg_analyzer.services.lazy_card_loader import LoadCardsResult


def _forest():
    return Card(id="Forest", name="Forest", type_line="Basic Land — Forest", is_land=True)


def _commander():
    return Card(
        id="Cmdr",
        name="Test Commander",
        type_line="Legendary Creature — Elf",
        is_creature=True,
        power=1,
        toughness=1,
        color_identity=set(),
    )


#: A structurally + Commander-legal deck (1 commander + 99 basics) — only
#: legal decks may start a goldfish game.
LEGAL_DECK = {
    "commanderText": "1 Test Commander\n",
    "mainboardText": "99 Forest\n",
    "shuffle": False,
}


class _FakeLoader:
    """Resolves a fixed set of names without touching Scryfall."""

    def __init__(self, cards: dict[str, Card]) -> None:
        self._cards = cards

    def load_cards(self, names):
        found = {n: self._cards[n] for n in names if n in self._cards}
        not_found = [n for n in names if n not in self._cards]
        return LoadCardsResult(cards=found, not_found=not_found)


def _setup(cards=None):
    manager = GameSessionManager()
    deck_db = DeckDatabase()
    default = {"Forest": _forest(), "Test Commander": _commander()}
    loader = _FakeLoader(cards if cards is not None else default)
    app.dependency_overrides[get_game_session_manager] = lambda: manager
    app.dependency_overrides[get_deck_database] = lambda: deck_db
    app.dependency_overrides[get_lazy_card_loader] = lambda: loader
    return manager, deck_db


def _teardown():
    for dep in (get_game_session_manager, get_deck_database, get_lazy_card_loader):
        app.dependency_overrides.pop(dep, None)


class TestStartGoldfish:
    def teardown_method(self):
        _teardown()

    def test_start_from_legal_decklist_text(self):
        _setup()
        client = TestClient(app)
        response = client.post("/api/game/goldfish", json=LEGAL_DECK)
        assert response.status_code == 200
        view = response.json()
        assert view["mode"] == "goldfish"
        assert view["state"]["turn_number"] == 1
        assert view["notFound"] == []
        # 99-card library minus a 7-card opening hand (commander is in the
        # command zone, not the library).
        assert view["state"]["players"][0]["library_count"] == 92

    def test_start_from_saved_deck_id(self):
        _, deck_db = _setup()
        from mtg_analyzer.models.deck import Deck

        deck = Deck(name="Mono-G", commander_text="1 Test Commander\n", mainboard_text="99 Forest\n")
        deck_db.save_deck(deck)
        client = TestClient(app)
        response = client.post("/api/game/goldfish", json={"deckId": deck.id, "shuffle": False})
        assert response.status_code == 200
        assert response.json()["state"]["players"][0]["library_count"] == 92

    def test_unknown_deck_id_is_404(self):
        _setup()
        client = TestClient(app)
        response = client.post("/api/game/goldfish", json={"deckId": "nope"})
        assert response.status_code == 404

    def test_illegal_deck_is_rejected(self):
        # Only legal decks may start (structurally illegal: 40 cards, no
        # commander) — the server enforces this even via a direct call.
        _setup()
        client = TestClient(app)
        response = client.post("/api/game/goldfish", json={"mainboardText": "40 Forest\n"})
        assert response.status_code == 422
        assert response.json()["detail"]["errors"]

    def test_legal_structure_but_unresolvable_is_422(self):
        _setup(cards={})  # structurally legal but nothing resolves
        client = TestClient(app)
        response = client.post("/api/game/goldfish", json=LEGAL_DECK)
        assert response.status_code == 422
        assert "Forest" in response.json()["detail"]["notFound"]


class TestSessionLifecycle:
    def teardown_method(self):
        _teardown()

    def _start(self, client):
        return client.post("/api/game/goldfish", json=LEGAL_DECK).json()

    def test_action_advance_and_rewind_and_restart(self):
        _setup()
        client = TestClient(app)
        view = self._start(client)
        sid = view["session_id"]

        # Advance a step.
        after = client.post(f"/api/game/{sid}/action", json={"type": "advance_step"}).json()
        assert after["can_rewind"] is True
        assert after["state"]["current_step"] == "untap"

        # Rewind it.
        rewound = client.post(f"/api/game/{sid}/rewind", json={"steps": 1}).json()
        assert rewound["can_rewind"] is False
        assert rewound["state"]["current_step"] == ""

        # Advance twice, then restart.
        client.post(f"/api/game/{sid}/action", json={"type": "advance_step"})
        client.post(f"/api/game/{sid}/action", json={"type": "advance_step"})
        restarted = client.post(f"/api/game/{sid}/restart").json()
        assert restarted["can_rewind"] is False
        assert restarted["state"]["turn_number"] == 1

    def test_get_session_returns_view(self):
        _setup()
        client = TestClient(app)
        sid = self._start(client)["session_id"]
        response = client.get(f"/api/game/{sid}")
        assert response.status_code == 200
        assert response.json()["session_id"] == sid

    def test_illegal_action_returns_400(self):
        _setup()
        client = TestClient(app)
        sid = self._start(client)["session_id"]
        # Playing a land during untap (before any advance) is illegal.
        state = client.get(f"/api/game/{sid}").json()["state"]
        hand = state["players"][0]["hand"]
        response = client.post(
            f"/api/game/{sid}/action",
            json={"type": "play_land", "instance_id": hand[0]["instance_id"]},
        )
        assert response.status_code == 400

    def test_delete_session(self):
        _setup()
        client = TestClient(app)
        sid = self._start(client)["session_id"]
        assert client.delete(f"/api/game/{sid}").status_code == 200
        assert client.get(f"/api/game/{sid}").status_code == 404

    def test_action_on_unknown_session_is_404(self):
        _setup()
        client = TestClient(app)
        response = client.post("/api/game/nope/action", json={"type": "advance_step"})
        assert response.status_code == 404


class TestMultiplayerStub:
    def teardown_method(self):
        _teardown()

    def test_multiplayer_returns_501(self):
        _setup()
        client = TestClient(app)
        response = client.post("/api/game/multiplayer")
        assert response.status_code == 501
