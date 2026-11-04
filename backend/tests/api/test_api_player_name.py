"""VIS-21: the account name is the only player name; anonymous seats are "Player".

Goldfisch, Solo and a blank Replay name the human seat server-side from the session and ignore
any client-sent name. Throwaway stores only.
"""

import pytest
from fastapi.testclient import TestClient

from mtg_analyzer.api.app import app
from mtg_analyzer.api.auth import session_cookie_name
from mtg_analyzer.api.dependencies import (
    get_account_store,
    get_deck_database,
    get_game_session_manager,
    get_lazy_card_loader,
)
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.decks.deck import Deck
from mtg_analyzer.services.account_store import ROLE_PLAYER, AccountStore
from mtg_analyzer.services.deck_database import DeckDatabase
from mtg_analyzer.services.game_session import FALLBACK_PLAYER_NAME, GameSessionManager
from mtg_analyzer.services.lazy_card_loader import LoadCardsResult

pytestmark = pytest.mark.real_auth

ACCOUNT_NAME = "Alice"
FOREST = Card(id="Forest", name="Forest", type_line="Basic Land — Forest", is_land=True)
COMMANDER = Card(
    id="Cmdr", name="Test Commander", type_line="Legendary Creature — Elf",
    is_creature=True, power=1, toughness=1, color_identity=set(),
)


class _Loader:
    _cards = {"Forest": FOREST, "Test Commander": COMMANDER}

    def load_cards(self, names):
        found = {n: self._cards[n] for n in names if n in self._cards}
        return LoadCardsResult(cards=found, not_found=[n for n in names if n not in self._cards])


@pytest.fixture
def world(tmp_path):
    accounts = AccountStore(tmp_path / "accounts.db")
    decks = DeckDatabase(tmp_path / "decks.db")
    deck = Deck(name="Global", commander_text="1 Test Commander\n", mainboard_text="99 Forest\n")
    decks.save_global(deck)
    app.dependency_overrides.update({
        get_account_store: lambda: accounts,
        get_deck_database: lambda: decks,
        get_game_session_manager: lambda: GameSessionManager(),
        get_lazy_card_loader: lambda: _Loader(),
    })
    acct = accounts.create_account_unchecked(ACCOUNT_NAME, "!", ROLE_PLAYER)
    token, session = accounts.create_session(acct.player_uuid)
    user = TestClient(app)
    user.cookies.set(session_cookie_name(), token)
    user.headers["X-CSRF-Token"] = session.csrf_token
    yield {"user": user, "anon": TestClient(app), "deck": deck}
    for dep in (get_account_store, get_deck_database, get_game_session_manager, get_lazy_card_loader):
        app.dependency_overrides.pop(dep, None)


def _names(view):
    return [p["name"] for p in view["state"]["players"]]


def _goldfish(client, deck, **extra):
    res = client.post("/api/game/goldfish", json={"deckId": deck.id, **extra})
    assert res.status_code == 200, res.text
    return res.json()


def _solo(client, deck, **extra):
    body = {"deckId": deck.id, "opponents": [{"kind": "goldfish", "deckId": deck.id}], **extra}
    res = client.post("/api/solo/start", json=body)
    assert res.status_code == 200, res.text
    return res.json()


def test_goldfish_seat_is_the_account_name_and_ignores_a_client_name(world):
    for extra in ({}, {"playerName": "Mallory", "player_name": "Mallory"}):
        assert _names(_goldfish(world["user"], world["deck"], **extra))[0] == ACCOUNT_NAME


def test_solo_seat_is_the_account_name_and_ignores_a_client_name(world):
    for extra in ({}, {"playerName": "Mallory"}):
        assert _names(_solo(world["user"], world["deck"], **extra))[0] == ACCOUNT_NAME


def test_blank_replay_seat_is_the_account_name(world):
    res = world["user"].post("/api/game/replay", json={"numPlayers": 2})
    assert res.status_code == 200, res.text
    assert _names(res.json())[0] == ACCOUNT_NAME


def test_anonymous_seats_are_player(world):
    assert FALLBACK_PLAYER_NAME == "Player"
    anon, deck = world["anon"], world["deck"]
    assert _names(_goldfish(anon, deck, playerName="Mallory"))[0] == FALLBACK_PLAYER_NAME
    assert _names(_solo(anon, deck, playerName="Mallory"))[0] == FALLBACK_PLAYER_NAME
    res = anon.post("/api/game/replay", json={"numPlayers": 1})
    assert _names(res.json())[0] == FALLBACK_PLAYER_NAME
