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


class TestDeckTokens:
    def teardown_method(self):
        _teardown()

    def test_lists_producible_tokens(self):
        rta = Card(id="RTA", name="Raise the Alarm", type_line="Instant", is_instant=True,
                   oracle_text="Create two 1/1 white Soldier creature tokens.")
        _setup({"Raise the Alarm": rta})
        client = TestClient(app)
        response = client.post("/api/game/deck-tokens", json={"mainboardText": "1 Raise the Alarm\n"})
        assert response.status_code == 200
        tokens = response.json()["tokens"]
        assert [t["name"] for t in tokens] == ["Soldier"]
        assert tokens[0]["power"] == 1 and tokens[0]["toughness"] == 1

    def test_empty_for_deck_without_token_makers(self):
        _setup()
        client = TestClient(app)
        # No legality gate here — this only preloads art.
        response = client.post("/api/game/deck-tokens", json={"mainboardText": "40 Forest\n"})
        assert response.status_code == 200
        assert response.json()["tokens"] == []

    def test_unknown_deck_id_is_404(self):
        _setup()
        client = TestClient(app)
        response = client.post("/api/game/deck-tokens", json={"deckId": "nope"})
        assert response.status_code == 404


class TestSessionLifecycle:
    def teardown_method(self):
        _teardown()

    def _start(self, client):
        return client.post("/api/game/goldfish", json=LEGAL_DECK).json()

    def _keep_opening_hand(self, client, sid):
        return client.post(
            f"/api/game/{sid}/action", json={"type": "keep_hand", "bottom_instance_ids": []}
        ).json()

    def test_action_advance_and_rewind_and_restart(self):
        _setup()
        client = TestClient(app)
        view = self._start(client)
        sid = view["session_id"]
        self._keep_opening_hand(client, sid)

        # Advance one step at a time (no auto-skip): the first step is untap.
        after = client.post(f"/api/game/{sid}/action", json={"type": "advance_step"}).json()
        assert after["can_rewind"] is True
        assert after["state"]["current_step"] == "untap"

        # Rewind it. `keep_hand` is itself an undoable action, so one
        # history entry (it) remains after undoing just the advance.
        rewound = client.post(f"/api/game/{sid}/rewind", json={"steps": 1}).json()
        assert rewound["can_rewind"] is True
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


class TestMulliganSetup:
    """A goldfish game starts in a setup phase: mulligan or keep the opening hand."""

    def teardown_method(self):
        _teardown()

    def _start(self, client):
        return client.post("/api/game/goldfish", json=LEGAL_DECK).json()

    def test_new_game_starts_in_setup_with_only_mulligan_actions(self):
        _setup()
        client = TestClient(app)
        view = self._start(client)
        assert view["setup"] == {"complete": False, "mulligan_count": 0, "draw_first": False}
        types = {a["type"] for a in view["legal_actions"]}
        assert types == {"mulligan", "keep_hand"}

    def test_other_actions_are_rejected_before_the_hand_is_kept(self):
        _setup()
        client = TestClient(app)
        sid = self._start(client)["session_id"]
        response = client.post(f"/api/game/{sid}/action", json={"type": "advance_step"})
        assert response.status_code == 400

    def test_mulligan_redraws_seven_and_requires_bottoming_one_to_keep(self):
        _setup()
        client = TestClient(app)
        sid = self._start(client)["session_id"]

        after_mull = client.post(f"/api/game/{sid}/action", json={"type": "mulligan"}).json()
        assert after_mull["setup"] == {"complete": False, "mulligan_count": 1, "draw_first": False}
        assert len(after_mull["state"]["players"][0]["hand"]) == 7
        keep_action = next(
            a for a in after_mull["legal_actions"] if a["type"] == "keep_hand"
        )
        assert keep_action["bottom_count"] == 1

        # Keeping without bottoming the required card is rejected.
        bad_keep = client.post(
            f"/api/game/{sid}/action", json={"type": "keep_hand", "bottom_instance_ids": []}
        )
        assert bad_keep.status_code == 400

        hand = after_mull["state"]["players"][0]["hand"]
        kept = client.post(
            f"/api/game/{sid}/action",
            json={"type": "keep_hand", "bottom_instance_ids": [hand[0]["instance_id"]]},
        ).json()
        assert kept["setup"] == {"complete": True, "mulligan_count": 1, "draw_first": False}
        assert len(kept["state"]["players"][0]["hand"]) == 6
        # The setup phase is over — normal actions are accepted again.
        response = client.post(f"/api/game/{sid}/action", json={"type": "advance_step"})
        assert response.status_code == 200

    def test_keeping_the_first_hand_needs_no_bottoming(self):
        _setup()
        client = TestClient(app)
        sid = self._start(client)["session_id"]
        kept = client.post(
            f"/api/game/{sid}/action", json={"type": "keep_hand", "bottom_instance_ids": []}
        ).json()
        assert kept["setup"]["complete"] is True
        assert len(kept["state"]["players"][0]["hand"]) == 7

    def test_restart_re_enters_the_setup_phase(self):
        _setup()
        client = TestClient(app)
        sid = self._start(client)["session_id"]
        client.post(f"/api/game/{sid}/action", json={"type": "keep_hand", "bottom_instance_ids": []})
        restarted = client.post(f"/api/game/{sid}/restart").json()
        assert restarted["setup"] == {"complete": False, "mulligan_count": 0, "draw_first": False}


class TestMultiplayerStub:
    def teardown_method(self):
        _teardown()

    def test_multiplayer_returns_501(self):
        _setup()
        client = TestClient(app)
        response = client.post("/api/game/multiplayer")
        assert response.status_code == 501
