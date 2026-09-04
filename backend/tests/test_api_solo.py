"""Tests for the solo-vs-bots HTTP API (PLR-14, `mtg_analyzer/api/solo.py`).

The Multiplayer engine without the lobby: one human seat (`SOLO_HUMAN_ID`),
1-3 `services/bots.py` bots, plain REST. These exercise the whole loop —
start → mulligan → play, with the bots answering synchronously after every
human action (`_advance_solo_bots`) — plus the RULE 400.2 redaction that a
solo-but-still-multiplayer session applies to the bot seats' hands.
"""

import pytest
from fastapi.testclient import TestClient

from mtg_analyzer.api.app import app
from mtg_analyzer.api.dependencies import (
    get_deck_database,
    get_game_session_manager,
    get_lazy_card_loader,
)
from mtg_analyzer.api.solo import SOLO_HUMAN_ID
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.deck import Deck
from mtg_analyzer.services.deck_database import DeckDatabase
from mtg_analyzer.services.game_session import GameSessionManager
from mtg_analyzer.services.lazy_card_loader import LoadCardsResult


def _forest():
    return Card(id="Forest", name="Forest", type_line="Basic Land — Forest", is_land=True)


def _commander():
    return Card(
        id="Cmdr", name="Test Commander", type_line="Legendary Creature — Elf",
        is_creature=True, power=1, toughness=1, color_identity=set(),
    )


class _FakeLoader:
    def __init__(self, cards):
        self._cards = cards

    def load_cards(self, names):
        found = {n: self._cards[n] for n in names if n in self._cards}
        return LoadCardsResult(cards=found, not_found=[n for n in names if n not in self._cards])


@pytest.fixture
def env():
    sessions = GameSessionManager()
    decks = DeckDatabase()
    loader = _FakeLoader({"Forest": _forest(), "Test Commander": _commander()})
    app.dependency_overrides[get_game_session_manager] = lambda: sessions
    app.dependency_overrides[get_deck_database] = lambda: decks
    app.dependency_overrides[get_lazy_card_loader] = lambda: loader
    yield {"client": TestClient(app), "sessions": sessions, "decks": decks}
    for dep in (get_game_session_manager, get_deck_database, get_lazy_card_loader):
        app.dependency_overrides.pop(dep, None)


def _legal_deck(decks, name="Mono-G"):
    deck = Deck(name=name, commander_text="1 Test Commander\n", mainboard_text="99 Forest\n")
    decks.save_deck(deck)
    return deck


_SENTINEL = object()


def _start(client, deck_id, opponents=_SENTINEL, **kw):
    if opponents is _SENTINEL:
        opponents = [{"kind": "goldfish", "deckId": deck_id}]
    return client.post(
        "/api/solo/start", json={"deckId": deck_id, "opponents": opponents, **kw}
    )


def _bot_ids(view):
    return [p["id"] for p in view["state"]["players"] if p["id"] != SOLO_HUMAN_ID]


def _controls(view, player_id, *, is_land=None):
    out = [o for o in view["state"]["battlefield"] if o.get("controller_id") == player_id]
    if is_land is not None:
        out = [o for o in out if bool(o.get("is_land")) == is_land]
    return out


# -- start ----------------------------------------------------------------


def test_start_returns_the_human_view_in_setup_with_the_bot_seated(env):
    client, decks = env["client"], env["decks"]
    deck = _legal_deck(decks)
    res = _start(client, deck.id)
    assert res.status_code == 200, res.json()
    view = res.json()
    assert view["perspective"] == SOLO_HUMAN_ID
    assert view["mode"] == "multiplayer"  # the engine underneath
    assert view["setup"] and not view["setup"]["complete"]
    ids = [p["id"] for p in view["state"]["players"]]
    assert SOLO_HUMAN_ID in ids and len(ids) == 2


def test_start_rejects_an_unknown_deck(env):
    res = _start(env["client"], "does-not-exist")
    assert res.status_code == 422


def test_start_rejects_zero_and_too_many_opponents(env):
    client, decks = env["client"], env["decks"]
    deck = _legal_deck(decks)
    assert _start(client, deck.id, opponents=[]).status_code == 400
    four = [{"kind": "goldfish", "deckId": deck.id} for _ in range(4)]
    assert _start(client, deck.id, opponents=four).status_code == 400


def test_start_rejects_an_unknown_bot_kind(env):
    client, decks = env["client"], env["decks"]
    deck = _legal_deck(decks)
    res = _start(client, deck.id, opponents=[{"kind": "wizard", "deckId": deck.id}])
    assert res.status_code == 400


def test_the_bots_hand_is_redacted_from_the_human_view(env):
    client, decks = env["client"], env["decks"]
    deck = _legal_deck(decks)
    view = _start(client, deck.id).json()
    bot_id = _bot_ids(view)[0]
    bot = next(p for p in view["state"]["players"] if p["id"] == bot_id)
    me = next(p for p in view["state"]["players"] if p["id"] == SOLO_HUMAN_ID)
    # RULE 400.2 — the human sees their own opening hand, not the bot's.
    assert len(me["hand"]) == 7
    assert not any(c.get("name") for c in bot["hand"]), bot["hand"]


# -- playing ------------------------------------------------------------------


def _session_id(view):
    return view["session_id"]


def test_keep_hand_completes_setup_and_hands_the_human_priority(env):
    client, decks = env["client"], env["decks"]
    deck = _legal_deck(decks)
    view = _start(client, deck.id).json()
    sid = _session_id(view)
    res = client.post(f"/api/solo/{sid}/action", json={"type": "keep_hand", "bottom_instance_ids": []})
    assert res.status_code == 200, res.json()
    view = res.json()
    assert view["setup"]["complete"]
    # The human is seat 0 (on the play) — it's their turn, and they have
    # actions to take (at minimum, passing priority).
    assert view["state"]["active_player_id"] == SOLO_HUMAN_ID
    assert view["legal_actions"]


def test_passing_through_the_turn_lets_the_bot_play_a_land(env):
    client, decks = env["client"], env["decks"]
    deck = _legal_deck(decks)
    view = _start(client, deck.id).json()
    sid = _session_id(view)
    client.post(f"/api/solo/{sid}/action", json={"type": "keep_hand", "bottom_instance_ids": []})
    bot_id = _bot_ids(view)[0]

    for _ in range(80):
        view = client.post(f"/api/solo/{sid}/action", json={"type": "pass_priority"}).json()
        if view.get("state", {}).get("game_over"):
            break
        if _controls(view, bot_id, is_land=True):
            break
    # The GoldfishBot plays a land every one of its turns — by the time the
    # game has come back around to the human a few times, one is on the board.
    assert _controls(view, bot_id, is_land=True), (
        f"turn {view['state']['turn_number']}, bot board {_controls(view, bot_id)}"
    )


def test_advance_solo_bots_terminates_on_a_bot_only_stretch(env):
    """`_advance_solo_bots` must never spin: after the human passes on their
    own turn with nothing on the stack, the bot takes a whole turn and the
    request still returns (the human gets priority back, or the game ends)."""
    client, decks = env["client"], env["decks"]
    deck = _legal_deck(decks)
    view = _start(client, deck.id).json()
    sid = _session_id(view)
    client.post(f"/api/solo/{sid}/action", json={"type": "keep_hand", "bottom_instance_ids": []})
    start_turn = view["state"]["turn_number"]
    for _ in range(40):
        view = client.post(f"/api/solo/{sid}/action", json={"type": "pass_priority"}).json()
    assert view["state"]["turn_number"] > start_turn  # the game moved on
    assert view["legal_actions"] or view["state"]["game_over"]


def test_the_human_is_never_handed_an_empty_priority_window_on_the_bots_turn(env):
    """A bot's turn is auto-passed for the human server-side: the view only
    comes back when the human has something to do (its own turn, a block, a
    real option) — never just to click "pass" through the opponent's upkeep,
    draw, combat and so on, which read as the table hanging (PLR-14)."""
    client, decks = env["client"], env["decks"]
    deck = _legal_deck(decks)
    view = _start(client, deck.id).json()
    sid = _session_id(view)
    client.post(f"/api/solo/{sid}/action", json={"type": "keep_hand", "bottom_instance_ids": []})

    saw_own_turn_again = False
    for _ in range(60):
        view = client.post(f"/api/solo/{sid}/action", json={"type": "pass_priority"}).json()
        state = view["state"]
        if state["game_over"]:
            break
        # Every view handed back is one the human genuinely has to act on.
        if state["active_player_id"] != SOLO_HUMAN_ID:
            only_pass = {a["type"] for a in view["legal_actions"]} <= {"pass_priority"}
            assert not only_pass, (
                f"handed an empty pass-only window on the bot's turn: "
                f"{state['turn_number']}/{state['current_step']}"
            )
        elif state["turn_number"] > 1:
            saw_own_turn_again = True
    assert saw_own_turn_again  # the loop really did cross a bot turn


# -- concede / restart / lifecycle ------------------------------------------


def test_concede_ends_the_game_in_the_bots_favour(env):
    client, decks = env["client"], env["decks"]
    deck = _legal_deck(decks)
    view = _start(client, deck.id).json()
    sid = _session_id(view)
    client.post(f"/api/solo/{sid}/action", json={"type": "keep_hand", "bottom_instance_ids": []})
    view = client.post(f"/api/solo/{sid}/concede").json()
    assert view["state"]["game_over"]
    assert view["state"]["winner_id"] in _bot_ids(view)


def test_restart_returns_to_setup_with_the_bot_kept_again(env):
    client, decks = env["client"], env["decks"]
    deck = _legal_deck(decks)
    view = _start(client, deck.id).json()
    sid = _session_id(view)
    client.post(f"/api/solo/{sid}/action", json={"type": "keep_hand", "bottom_instance_ids": []})
    view = client.post(f"/api/solo/{sid}/restart").json()
    assert view["setup"] and not view["setup"]["complete"]
    assert view["state"]["active_player_id"] == SOLO_HUMAN_ID


def test_get_view_and_delete(env):
    client, decks = env["client"], env["decks"]
    deck = _legal_deck(decks)
    sid = _session_id(_start(client, deck.id).json())
    assert client.get(f"/api/solo/{sid}").json()["perspective"] == SOLO_HUMAN_ID
    assert client.delete(f"/api/solo/{sid}").json() == {"deleted": True}
    assert client.get(f"/api/solo/{sid}").status_code == 404
    assert client.delete(f"/api/solo/{sid}").status_code == 404
