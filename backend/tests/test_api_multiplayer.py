"""Tests for the multiplayer lobby + game HTTP/WebSocket API (UC4).

Reference: mtg_analyzer/api/multiplayer.py, mtg_analyzer/api/multiplayer_ws.py,
mtg_analyzer/services/lobby.py.

The lobby half (presence, forming a table, accepting) is exercised through
the REST routes; the `/ws/lobby` half is exercised with FastAPI's test
WebSocket client, since presence is defined by holding that socket.
"""

import pytest
from fastapi.testclient import TestClient

from mtg_analyzer.api.app import app
from mtg_analyzer.api.dependencies import (
    get_deck_database,
    get_game_session_manager,
    get_lazy_card_loader,
    get_lobby,
)
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.deck import Deck
from mtg_analyzer.services.deck_database import DeckDatabase
from mtg_analyzer.services.game_session import GameSessionManager
from mtg_analyzer.services.lazy_card_loader import LoadCardsResult
from mtg_analyzer.services.lobby import AVAILABLE, ONLINE, PLAYING, Lobby


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


class _FakeLoader:
    def __init__(self, cards):
        self._cards = cards

    def load_cards(self, names):
        found = {n: self._cards[n] for n in names if n in self._cards}
        return LoadCardsResult(
            cards=found, not_found=[n for n in names if n not in self._cards]
        )


@pytest.fixture
def env():
    """A fresh lobby/session manager/deck database wired into the app."""
    lobby = Lobby()
    sessions = GameSessionManager()
    decks = DeckDatabase()
    loader = _FakeLoader({"Forest": _forest(), "Test Commander": _commander()})
    app.dependency_overrides[get_lobby] = lambda: lobby
    app.dependency_overrides[get_game_session_manager] = lambda: sessions
    app.dependency_overrides[get_deck_database] = lambda: decks
    app.dependency_overrides[get_lazy_card_loader] = lambda: loader
    yield {
        "client": TestClient(app),
        "lobby": lobby,
        "sessions": sessions,
        "decks": decks,
    }
    for dep in (get_lobby, get_game_session_manager, get_deck_database, get_lazy_card_loader):
        app.dependency_overrides.pop(dep, None)


def _legal_deck(decks, name="Mono-G"):
    deck = Deck(name=name, commander_text="1 Test Commander\n", mainboard_text="99 Forest\n")
    decks.save_deck(deck)
    return deck


def _connect(client, name):
    return client.post("/api/multiplayer/connect", json={"name": name}).json()["player"]["id"]


def _seated_game(env):
    """A two-seat table with both decks chosen and both players accepted."""
    client, decks = env["client"], env["decks"]
    ann, bob = _connect(client, "Ann"), _connect(client, "Bob")
    deck = _legal_deck(decks)
    game_id = client.post(
        "/api/multiplayer/games", json={"playerId": ann, "name": "Testtisch"}
    ).json()["game"]["id"]
    client.post(f"/api/multiplayer/games/{game_id}/join", json={"playerId": bob})
    # Decks first, then acceptance — picking a deck is a change to the table
    # and clears every seat's acceptance (see `Lobby.set_deck`).
    for pid in (ann, bob):
        client.post(
            f"/api/multiplayer/games/{game_id}/deck", json={"playerId": pid, "deckId": deck.id}
        )
    for pid in (ann, bob):
        client.post(f"/api/multiplayer/games/{game_id}/ready", json={"playerId": pid})
    return game_id, ann, bob


class TestLobby:
    def test_connect_assigns_an_id_and_lists_the_player(self, env):
        client = env["client"]
        body = client.post("/api/multiplayer/connect", json={"name": "Ann"}).json()
        assert body["player"]["state"] == ONLINE
        assert [p["name"] for p in body["lobby"]["players"]] == ["Ann"]

    def test_reconnecting_with_an_id_keeps_the_same_player(self, env):
        client = env["client"]
        pid = _connect(client, "Ann")
        again = client.post(
            "/api/multiplayer/connect", json={"name": "Ann", "playerId": pid}
        ).json()
        assert again["player"]["id"] == pid
        assert len(again["lobby"]["players"]) == 1

    def test_creating_a_game_seats_the_host_and_marks_them_playing(self, env):
        client = env["client"]
        ann = _connect(client, "Ann")
        body = client.post("/api/multiplayer/games", json={"playerId": ann}).json()
        game = body["game"]
        assert game["host_id"] == ann
        assert [s["player_id"] for s in game["seats"]] == [ann]
        assert env["lobby"].player(ann).state == PLAYING

    def test_joining_a_full_game_is_refused(self, env):
        client = env["client"]
        ann, bob, cid = (_connect(client, n) for n in ("Ann", "Bob", "Cid"))
        gid = client.post("/api/multiplayer/games", json={"playerId": ann}).json()["game"]["id"]
        client.post(f"/api/multiplayer/games/{gid}/join", json={"playerId": bob})
        response = client.post(f"/api/multiplayer/games/{gid}/join", json={"playerId": cid})
        assert response.status_code == 400

    def test_leaving_the_last_seat_drops_the_table(self, env):
        client = env["client"]
        ann = _connect(client, "Ann")
        gid = client.post("/api/multiplayer/games", json={"playerId": ann}).json()["game"]["id"]
        body = client.post(f"/api/multiplayer/games/{gid}/leave", json={"playerId": ann}).json()
        assert body["game"] is None
        assert body["lobby"]["games"] == []
        assert env["lobby"].player(ann).state == AVAILABLE

    def test_choosing_a_deck_clears_everyone_elses_acceptance(self, env):
        client, decks = env["client"], env["decks"]
        ann, bob = _connect(client, "Ann"), _connect(client, "Bob")
        deck = _legal_deck(decks)
        gid = client.post("/api/multiplayer/games", json={"playerId": ann}).json()["game"]["id"]
        client.post(f"/api/multiplayer/games/{gid}/join", json={"playerId": bob})
        client.post(
            f"/api/multiplayer/games/{gid}/deck", json={"playerId": ann, "deckId": deck.id}
        )
        client.post(f"/api/multiplayer/games/{gid}/ready", json={"playerId": ann})
        # Bob picking a deck changes the table, so Ann's acceptance lapses.
        body = client.post(
            f"/api/multiplayer/games/{gid}/deck", json={"playerId": bob, "deckId": deck.id}
        ).json()
        assert [s["ready"] for s in body["game"]["seats"]] == [False, False]

    def test_accepting_without_a_deck_is_refused(self, env):
        client = env["client"]
        ann = _connect(client, "Ann")
        gid = client.post("/api/multiplayer/games", json={"playerId": ann}).json()["game"]["id"]
        response = client.post(f"/api/multiplayer/games/{gid}/ready", json={"playerId": ann})
        assert response.status_code == 400

    def test_only_the_host_can_change_the_settings(self, env):
        client = env["client"]
        ann, bob = _connect(client, "Ann"), _connect(client, "Bob")
        gid = client.post("/api/multiplayer/games", json={"playerId": ann}).json()["game"]["id"]
        client.post(f"/api/multiplayer/games/{gid}/join", json={"playerId": bob})
        assert (
            client.post(
                f"/api/multiplayer/games/{gid}/options",
                json={"playerId": bob, "mulliganStyle": "none"},
            ).status_code
            == 400
        )
        body = client.post(
            f"/api/multiplayer/games/{gid}/options",
            json={"playerId": ann, "mulliganStyle": "none"},
        ).json()
        assert body["game"]["mulligan_style"] == "none"

    def test_unknown_deck_is_404(self, env):
        client = env["client"]
        ann = _connect(client, "Ann")
        gid = client.post("/api/multiplayer/games", json={"playerId": ann}).json()["game"]["id"]
        response = client.post(
            f"/api/multiplayer/games/{gid}/deck", json={"playerId": ann, "deckId": "nope"}
        )
        assert response.status_code == 404


class TestStartingAndPlaying:
    def test_start_builds_a_session_and_deals_both_hands(self, env):
        client = env["client"]
        gid, ann, bob = _seated_game(env)
        body = client.post(f"/api/multiplayer/games/{gid}/start", json={"playerId": ann}).json()
        assert body["game"]["status"] == "running"
        view = body["view"]
        assert view["mode"] == "multiplayer"
        assert view["perspective"] == ann
        players = {p["id"]: p for p in view["state"]["players"]}
        assert len(players[ann]["hand"]) == 7
        assert players[bob]["hand"] == []  # RULE 400.2, redacted server-side

    def test_start_is_refused_until_everyone_accepts(self, env):
        client, decks = env["client"], env["decks"]
        ann, bob = _connect(client, "Ann"), _connect(client, "Bob")
        deck = _legal_deck(decks)
        gid = client.post("/api/multiplayer/games", json={"playerId": ann}).json()["game"]["id"]
        client.post(f"/api/multiplayer/games/{gid}/join", json={"playerId": bob})
        client.post(
            f"/api/multiplayer/games/{gid}/deck", json={"playerId": ann, "deckId": deck.id}
        )
        client.post(f"/api/multiplayer/games/{gid}/ready", json={"playerId": ann})
        response = client.post(f"/api/multiplayer/games/{gid}/start", json={"playerId": ann})
        assert response.status_code == 400

    def test_an_illegal_deck_blocks_the_start_and_names_its_owner(self, env):
        client, decks = env["client"], env["decks"]
        ann, bob = _connect(client, "Ann"), _connect(client, "Bob")
        good = _legal_deck(decks)
        bad = Deck(name="Zu klein", mainboard_text="40 Forest\n")
        decks.save_deck(bad)
        gid = client.post("/api/multiplayer/games", json={"playerId": ann}).json()["game"]["id"]
        client.post(f"/api/multiplayer/games/{gid}/join", json={"playerId": bob})
        client.post(
            f"/api/multiplayer/games/{gid}/deck", json={"playerId": ann, "deckId": good.id}
        )
        client.post(f"/api/multiplayer/games/{gid}/deck", json={"playerId": bob, "deckId": bad.id})
        client.post(f"/api/multiplayer/games/{gid}/ready", json={"playerId": ann})
        client.post(f"/api/multiplayer/games/{gid}/ready", json={"playerId": bob})
        response = client.post(f"/api/multiplayer/games/{gid}/start", json={"playerId": ann})
        assert response.status_code == 422
        assert response.json()["detail"]["player_id"] == bob

    def test_each_seat_gets_its_own_view(self, env):
        client = env["client"]
        gid, ann, bob = _seated_game(env)
        client.post(f"/api/multiplayer/games/{gid}/start", json={"playerId": ann})
        for me, other in ((ann, bob), (bob, ann)):
            view = client.get(f"/api/multiplayer/games/{gid}", params={"player_id": me}).json()[
                "view"
            ]
            players = {p["id"]: p for p in view["state"]["players"]}
            assert len(players[me]["hand"]) == 7
            assert players[other]["hand"] == []

    def test_an_observer_sees_the_board_and_no_hands(self, env):
        client = env["client"]
        gid, ann, _bob = _seated_game(env)
        client.post(f"/api/multiplayer/games/{gid}/start", json={"playerId": ann})
        watcher = _connect(client, "Watcher")
        body = client.post(
            f"/api/multiplayer/games/{gid}/observe", json={"playerId": watcher}
        ).json()
        assert watcher in body["game"]["observer_ids"]
        view = body["view"]
        assert view["observer"] is True
        assert all(p["hand"] == [] for p in view["state"]["players"])
        assert view["legal_actions"] == []

    def test_an_observer_cannot_act(self, env):
        client = env["client"]
        gid, ann, _bob = _seated_game(env)
        client.post(f"/api/multiplayer/games/{gid}/start", json={"playerId": ann})
        watcher = _connect(client, "Watcher")
        client.post(f"/api/multiplayer/games/{gid}/observe", json={"playerId": watcher})
        response = client.post(
            f"/api/multiplayer/games/{gid}/action",
            json={"playerId": watcher, "action": {"type": "advance_step"}},
        )
        assert response.status_code == 403

    def test_a_seat_cannot_join_a_running_game(self, env):
        client = env["client"]
        gid, ann, _bob = _seated_game(env)
        client.post(f"/api/multiplayer/games/{gid}/start", json={"playerId": ann})
        late = _connect(client, "Late")
        assert (
            client.post(
                f"/api/multiplayer/games/{gid}/join", json={"playerId": late}
            ).status_code
            == 400
        )

    def test_acting_before_the_game_starts_is_a_409(self, env):
        client = env["client"]
        gid, ann, _bob = _seated_game(env)
        response = client.post(
            f"/api/multiplayer/games/{gid}/action",
            json={"playerId": ann, "action": {"type": "advance_step"}},
        )
        assert response.status_code == 409

    def test_an_illegal_action_is_a_400_and_changes_nothing(self, env):
        client = env["client"]
        gid, ann, bob = _seated_game(env)
        client.post(f"/api/multiplayer/games/{gid}/start", json={"playerId": ann})
        for pid in (ann, bob):
            client.post(
                f"/api/multiplayer/games/{gid}/action",
                json={"playerId": pid, "action": {"type": "keep_hand", "bottom_instance_ids": []}},
            )
        # Both kept, so play has begun and Ann (seat 1) holds priority.
        before = client.get(
            f"/api/multiplayer/games/{gid}", params={"player_id": ann}
        ).json()["view"]
        assert before["priority"] == {"interactive": True, "player_id": ann, "passed": []}

        # Bob doesn't hold priority, so he can't pass it (RULE 117.1).
        response = client.post(
            f"/api/multiplayer/games/{gid}/action",
            json={"playerId": bob, "action": {"type": "pass_priority"}},
        )
        assert response.status_code == 400
        view = client.get(f"/api/multiplayer/games/{gid}", params={"player_id": ann}).json()["view"]
        assert view["priority"] == before["priority"]  # untouched
        assert view["state"]["current_step"] == before["state"]["current_step"]

    def test_conceding_ends_the_game_and_closes_the_table(self, env):
        client = env["client"]
        gid, ann, bob = _seated_game(env)
        client.post(f"/api/multiplayer/games/{gid}/start", json={"playerId": ann})
        body = client.post(f"/api/multiplayer/games/{gid}/concede", json={"playerId": bob}).json()
        assert body["view"]["state"]["game_over"] is True
        assert body["view"]["state"]["winner_id"] == ann
        assert body["game"]["status"] == "finished"
        assert body["game"]["conceded_ids"] == [bob]


class TestLobbyWebSocket:
    def test_connecting_registers_the_player_and_returns_an_id(self, env):
        client = env["client"]
        with client.websocket_connect("/ws/lobby?name=Ann") as socket:
            welcome = socket.receive_json()
            assert welcome["type"] == "welcome"
            assert welcome["player_id"]
            assert [p["name"] for p in welcome["lobby"]["players"]] == ["Ann"]

    def test_presence_reports_available_and_broadcasts(self, env):
        client = env["client"]
        with client.websocket_connect("/ws/lobby?name=Ann") as socket:
            welcome = socket.receive_json()
            _drain_until(socket, "lobby_update")  # the connect broadcasts
            socket.send_json({"type": "presence", "state": AVAILABLE})
            update = _drain_until(socket, "lobby_update")
            assert update["lobby"]["players"][0]["state"] == AVAILABLE
            assert env["lobby"].player(welcome["player_id"]).state == AVAILABLE

    def test_a_player_in_a_game_stays_playing(self, env):
        client = env["client"]
        with client.websocket_connect("/ws/lobby?name=Ann") as socket:
            player_id = socket.receive_json()["player_id"]
            client.post("/api/multiplayer/games", json={"playerId": player_id})
            # Even if the client claims to be idling in the lobby, holding a
            # seat is what decides the state.
            env["lobby"].set_presence(player_id, AVAILABLE)
            assert env["lobby"].player(player_id).state == PLAYING

    def test_disconnecting_removes_the_player(self, env):
        client = env["client"]
        with client.websocket_connect("/ws/lobby?name=Ann") as socket:
            socket.receive_json()
        assert client.get("/api/multiplayer/lobby").json()["players"] == []

    def test_a_move_is_pushed_to_both_seats_with_their_own_view(self, env):
        client = env["client"]
        with client.websocket_connect("/ws/lobby?name=Ann") as ann_socket:
            ann = ann_socket.receive_json()["player_id"]
            with client.websocket_connect("/ws/lobby?name=Bob") as bob_socket:
                bob = bob_socket.receive_json()["player_id"]
                deck = _legal_deck(env["decks"])
                gid = client.post(
                    "/api/multiplayer/games", json={"playerId": ann}
                ).json()["game"]["id"]
                client.post(f"/api/multiplayer/games/{gid}/join", json={"playerId": bob})
                for pid in (ann, bob):
                    client.post(
                        f"/api/multiplayer/games/{gid}/deck",
                        json={"playerId": pid, "deckId": deck.id},
                    )
                for pid in (ann, bob):
                    client.post(f"/api/multiplayer/games/{gid}/ready", json={"playerId": pid})
                client.post(f"/api/multiplayer/games/{gid}/start", json={"playerId": ann})

                pushed = _game_update_with_view(bob_socket)
                assert pushed is not None
                players = {p["id"]: p for p in pushed["view"]["state"]["players"]}
                # Bob's own socket got Bob's own hand — not Ann's.
                assert len(players[bob]["hand"]) == 7
                assert players[ann]["hand"] == []


def _drain_until(socket, message_type, limit=20):
    """The next message of ``message_type``, skipping whatever precedes it."""
    for _ in range(limit):
        message = socket.receive_json()
        if message.get("type") == message_type:
            return message
    raise AssertionError(f"no {message_type!r} message arrived")


def _game_update_with_view(socket, limit=40):
    """The first pushed `game_update` that actually carries a board.

    Every table change broadcasts one, but the ones from setup have no
    session behind them yet (``view: None``); the first with a view is the
    push that follows `start`.
    """
    for _ in range(limit):
        message = socket.receive_json()
        if message.get("type") == "game_update" and message.get("view"):
            return message
    return None


class TestReconnect:
    """A seat is held by *name*, so a reload doesn't cost you the game."""

    def test_reconnecting_with_the_same_name_reclaims_the_seat(self, env):
        client, lobby = env["client"], env["lobby"]
        gid, ann, _bob = _seated_game(env)
        client.post(f"/api/multiplayer/games/{gid}/start", json={"playerId": ann})

        # The socket goes away (a reload, a dropped connection) …
        import asyncio

        from mtg_analyzer.api.multiplayer_ws import handle_disconnect

        asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
            handle_disconnect(ann, lobby, env["sessions"])
        )
        assert lobby.player(ann).connected is False
        assert lobby.player(ann).game_id == gid  # seat held

        # … and the same name comes back to the same seat, same game.
        again = client.post("/api/multiplayer/connect", json={"name": "Ann"}).json()["player"]
        assert again["id"] == ann
        assert again["connected"] is True
        assert again["game_id"] == gid

    def test_a_different_capitalisation_is_the_same_player(self, env):
        client = env["client"]
        first = _connect(client, "Ann")
        again = client.post("/api/multiplayer/connect", json={"name": "  aNN "}).json()["player"]
        assert again["id"] == first
        assert again["name"] == "aNN"  # renamed to what they last typed

    def test_a_disconnected_lobby_player_with_no_seat_is_dropped(self, env):
        # Nothing to hold for them, and a ghost in the player list is worse
        # than no entry at all.
        lobby = env["lobby"]
        pid = _connect(env["client"], "Ann")
        lobby.disconnect(pid)
        assert lobby.find(pid) is None


class TestWatchdog:
    """`sweep_once`: idle disconnects, lapsed seats, and keeping play moving."""

    def _running(self, env):
        client = env["client"]
        gid, ann, bob = _seated_game(env)
        client.post(f"/api/multiplayer/games/{gid}/start", json={"playerId": ann})
        for pid in (ann, bob):
            client.post(
                f"/api/multiplayer/games/{gid}/action",
                json={"playerId": pid, "action": {"type": "keep_hand", "bottom_instance_ids": []}},
            )
        return gid, ann, bob

    def _sweep(self, env):
        import asyncio

        from mtg_analyzer.api.multiplayer_ws import sweep_once

        loop = asyncio.get_event_loop_policy().new_event_loop()
        try:
            loop.run_until_complete(sweep_once(env["lobby"], env["sessions"]))
        finally:
            loop.close()

    def _session(self, env, gid):
        return env["sessions"].get(env["lobby"].game(gid).session_id)

    def test_an_idle_priority_holder_is_disconnected(self, env, monkeypatch):
        monkeypatch.setattr("mtg_analyzer.services.lobby.MULTIPLAYER_IDLE_TIMEOUT_SECONDS", 0.0001)
        gid, ann, _bob = self._running(env)
        assert self._session(env, gid).engine.state.priority_player.id == ann

        import time

        time.sleep(0.01)
        self._sweep(env)
        assert env["lobby"].player(ann).connected is False

    def test_priority_is_passed_for_an_absent_player(self, env):
        gid, ann, _bob = self._running(env)
        session = self._session(env, gid)
        step_before = session.engine.state.current_step
        env["lobby"].disconnect(ann)

        self._sweep(env)
        # Ann isn't there to hold priority, so the server passed for her and
        # the table moved on rather than freezing (RULE 117 — passing is
        # always legal and never gains the absent player anything).
        assert session.engine.state.priority_player.id != ann or (
            session.engine.state.current_step != step_before
        )

    def test_a_lapsed_grace_period_concedes_the_seat(self, env, monkeypatch):
        monkeypatch.setattr(
            "mtg_analyzer.services.lobby.MULTIPLAYER_DISCONNECT_GRACE_SECONDS", 0.0001
        )
        gid, ann, bob = self._running(env)
        env["lobby"].disconnect(bob)

        import time

        time.sleep(0.01)
        self._sweep(env)
        session = self._session(env, gid)
        assert session.engine.state.players[1].loss_reason == "conceded"
        assert session.engine.state.game_over is True
        assert session.engine.state.winner_id == ann
        assert env["lobby"].game(gid).status == "finished"

    def test_a_connected_player_is_never_swept(self, env):
        gid, ann, bob = self._running(env)
        self._sweep(env)
        assert env["lobby"].player(ann).connected is True
        assert env["lobby"].player(bob).connected is True
        assert self._session(env, gid).engine.state.priority_player.id == ann

    def test_acting_resets_the_idle_timer(self, env):
        client = env["client"]
        gid, ann, _bob = self._running(env)
        before = env["lobby"].player(ann).last_action_at
        client.post(
            f"/api/multiplayer/games/{gid}/action",
            json={"playerId": ann, "action": {"type": "pass_priority"}},
        )
        assert env["lobby"].player(ann).last_action_at > before
