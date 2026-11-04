"""Tests for the multiplayer lobby + game HTTP/WebSocket API (UC4).

Reference: mtg_analyzer/api/multiplayer.py, mtg_analyzer/api/multiplayer_ws.py,
mtg_analyzer/services/lobby.py.

The lobby half (presence, forming a table, accepting) is exercised through
the REST routes; the `/ws/lobby` half is exercised with FastAPI's test
WebSocket client, since presence is defined by holding that socket.
"""

from tests.support.auth import TEST_PLAYER_UUID, account_header
import contextlib

import pytest
from fastapi.testclient import TestClient

from mp_player_client import PlayerClient
from mtg_analyzer.api.app import app
from mtg_analyzer.api.dependencies import (
    get_deck_database,
    get_game_session_manager,
    get_lazy_card_loader,
    get_lobby,
)
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.decks.deck import Deck
from mtg_analyzer.services.deck_database import DeckDatabase
from mtg_analyzer.services.game_session import GameSessionManager
from mtg_analyzer.services.lazy_card_loader import LoadCardsResult
from mtg_analyzer.services.lobby import (
    AVAILABLE,
    ONLINE,
    PLAYING,
    Lobby,
    normalize_banner_color,
)


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
def env(tmp_path, monkeypatch):
    from mtg_analyzer.services import mcp_credentials
    monkeypatch.setattr(mcp_credentials, "_path", lambda: tmp_path / "mcp_token")
    server_token = mcp_credentials.rotate_token()
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
        "client": PlayerClient(
            app, lobby=lobby, headers={"X-MCP-Server-Token": server_token}
        ),
        "mcp_server_token": server_token,
        "lobby": lobby,
        "sessions": sessions,
        "decks": decks,
    }
    for dep in (get_lobby, get_game_session_manager, get_deck_database, get_lazy_card_loader):
        app.dependency_overrides.pop(dep, None)


def _legal_deck(decks, name="Mono-G", color_identity=None):
    """A playable saved deck. ``color_identity`` is what a deck the client
    has already listed once carries (`api/saved_decks._ensure_identity`) —
    left `None` here by default, i.e. not computed yet, since most tests
    don't care and the banner default is explicitly written for both."""
    deck = Deck(
        name=name,
        commander_text="1 Test Commander\n",
        mainboard_text="99 Forest\n",
        color_identity=color_identity,
    )
    decks.save_global(deck)  # PLR-9c: several accounts sit at one table, so the deck must be readable by all
    return deck


def _battlefield_of(view, player_id):
    """The permanents ``player_id`` controls (the battlefield is shared)."""
    return [
        obj
        for obj in view["state"]["battlefield"]
        if obj.get("controller_id") == player_id
    ]


@contextlib.contextmanager
def lobby_socket(client, name, tab_id=None, headers=None):
    """An authenticated `/ws/lobby` socket for the fake account ``name`` (PLR-9c).

    Sends the handshake frame and yields ``(socket, welcome)``.
    """
    with client.websocket_connect("/ws/lobby", headers=headers or account_header(name)) as socket:
        socket.send_json({"type": "auth", **({"tab_id": tab_id} if tab_id else {})})
        yield socket, socket.receive_json()


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

    def test_takebacks_per_player_is_host_configurable_and_clamped(self, env):
        client = env["client"]
        ann, bob = _connect(client, "Ann"), _connect(client, "Bob")
        gid = client.post("/api/multiplayer/games", json={"playerId": ann}).json()["game"]["id"]
        client.post(f"/api/multiplayer/games/{gid}/join", json={"playerId": bob})
        body = client.post(
            f"/api/multiplayer/games/{gid}/options",
            json={"playerId": ann, "takebacksPerPlayer": 2},
        ).json()
        assert body["game"]["takebacks_per_player"] == 2
        # A silly value is clamped rather than accepted or rejected outright
        # — this is a table convenience, not something worth a 400 over.
        body = client.post(
            f"/api/multiplayer/games/{gid}/options",
            json={"playerId": ann, "takebacksPerPlayer": 9999},
        ).json()
        assert body["game"]["takebacks_per_player"] == 20

    def test_spell_timer_seconds_defaults_from_config_and_is_host_overridable(self, env):
        client = env["client"]
        ann, bob = _connect(client, "Ann"), _connect(client, "Bob")
        gid = client.post("/api/multiplayer/games", json={"playerId": ann}).json()["game"]["id"]
        client.post(f"/api/multiplayer/games/{gid}/join", json={"playerId": bob})
        # Not chosen yet: the table carries None and inherits the server value.
        created = client.post("/api/multiplayer/games", json={"playerId": _connect(client, "Cara")})
        assert created.json()["game"]["spell_timer_seconds"] is None
        body = client.post(
            f"/api/multiplayer/games/{gid}/options",
            json={"playerId": ann, "spellTimerSeconds": 8},
        ).json()
        assert body["game"]["spell_timer_seconds"] == 8
        # 0 is a real value (countdown off), not "unset".
        body = client.post(
            f"/api/multiplayer/games/{gid}/options",
            json={"playerId": ann, "spellTimerSeconds": 0},
        ).json()
        assert body["game"]["spell_timer_seconds"] == 0
        # Clamped, same as takebacks.
        body = client.post(
            f"/api/multiplayer/games/{gid}/options",
            json={"playerId": ann, "spellTimerSeconds": 99999},
        ).json()
        assert body["game"]["spell_timer_seconds"] == 600

    def test_randomization_options_round_trip(self, env):
        """RULE 103.1/103.2 — the camelCase aliases have to reach the lobby.

        The logic itself is `LobbyGame.seating_order`'s (see
        test_multiplayer_pods.py); what this guards is the wiring, which is
        exactly where a new option silently goes nowhere.
        """
        client = env["client"]
        ann, bob = _connect(client, "Ann"), _connect(client, "Bob")
        created = client.post("/api/multiplayer/games", json={"playerId": ann}).json()["game"]
        gid = created["id"]
        client.post(f"/api/multiplayer/games/{gid}/join", json={"playerId": bob})
        # Both off by default: a table that says nothing keeps join order.
        assert created["randomize_seating"] is False
        assert created["random_starting_player"] is False

        body = client.post(
            f"/api/multiplayer/games/{gid}/options",
            json={"playerId": ann, "randomizeSeating": True, "randomStartingPlayer": True},
        ).json()
        assert body["game"]["randomize_seating"] is True
        assert body["game"]["random_starting_player"] is True

        # And they can be turned back off — a `False` must not read as "unset".
        body = client.post(
            f"/api/multiplayer/games/{gid}/options",
            json={"playerId": ann, "randomizeSeating": False},
        ).json()
        assert body["game"]["randomize_seating"] is False
        assert body["game"]["random_starting_player"] is True

    def test_unknown_deck_is_404(self, env):
        client = env["client"]
        ann = _connect(client, "Ann")
        gid = client.post("/api/multiplayer/games", json={"playerId": ann}).json()["game"]["id"]
        response = client.post(
            f"/api/multiplayer/games/{gid}/deck", json={"playerId": ann, "deckId": "nope"}
        )
        assert response.status_code == 404


class TestGameFormatOptions:
    """PLR-13: the format (+ Archenemy seat) picker in Multiplayer Setup."""

    def test_unknown_format_is_rejected(self, env):
        client = env["client"]
        ann, bob = _connect(client, "Ann"), _connect(client, "Bob")
        gid = client.post("/api/multiplayer/games", json={"playerId": ann}).json()["game"]["id"]
        client.post(f"/api/multiplayer/games/{gid}/join", json={"playerId": bob})
        response = client.post(
            f"/api/multiplayer/games/{gid}/options",
            json={"playerId": ann, "gameFormat": "nonsense"},
        )
        assert response.status_code == 400

    def test_format_and_archenemy_round_trip(self, env):
        client = env["client"]
        ann, bob = _connect(client, "Ann"), _connect(client, "Bob")
        gid = client.post("/api/multiplayer/games", json={"playerId": ann}).json()["game"]["id"]
        client.post(f"/api/multiplayer/games/{gid}/join", json={"playerId": bob})
        body = client.post(
            f"/api/multiplayer/games/{gid}/options",
            json={"playerId": ann, "gameFormat": "archenemy", "archenemyId": bob},
        ).json()
        assert body["game"]["game_format"] == "archenemy"
        assert body["game"]["archenemy_id"] == bob

    def test_only_the_host_can_change_the_format(self, env):
        client = env["client"]
        ann, bob = _connect(client, "Ann"), _connect(client, "Bob")
        gid = client.post("/api/multiplayer/games", json={"playerId": ann}).json()["game"]["id"]
        client.post(f"/api/multiplayer/games/{gid}/join", json={"playerId": bob})
        response = client.post(
            f"/api/multiplayer/games/{gid}/options",
            json={"playerId": bob, "gameFormat": "planechase"},
        )
        assert response.status_code == 400

    def test_starting_an_archenemy_table_applies_it_to_the_real_session(self, env):
        """The seam PLR-13 actually closes: a lobby setting reaching the
        engine, not just `build_multiplayer_engine` in isolation (see
        test_game_session.py's `TestGameFormatThreading` for that half)."""
        client, decks = env["client"], env["decks"]
        ann, bob = _connect(client, "Ann"), _connect(client, "Bob")
        deck = _legal_deck(decks)
        gid = client.post("/api/multiplayer/games", json={"playerId": ann}).json()["game"]["id"]
        client.post(f"/api/multiplayer/games/{gid}/join", json={"playerId": bob})
        client.post(
            f"/api/multiplayer/games/{gid}/options",
            json={"playerId": ann, "gameFormat": "archenemy", "archenemyId": bob},
        )
        for pid in (ann, bob):
            client.post(f"/api/multiplayer/games/{gid}/deck", json={"playerId": pid, "deckId": deck.id})
        for pid in (ann, bob):
            client.post(f"/api/multiplayer/games/{gid}/ready", json={"playerId": pid})
        body = client.post(f"/api/multiplayer/games/{gid}/start", json={"playerId": ann}).json()
        state = body["view"]["state"]
        assert state["format"] == "archenemy"
        assert state["archenemy_id"] == bob
        bob_player = next(p for p in state["players"] if p["id"] == bob)
        assert bob_player["life"] == 40  # RULE 904.4

    def test_archenemy_defaults_to_the_host_when_not_chosen(self, env):
        client, decks = env["client"], env["decks"]
        ann, bob = _connect(client, "Ann"), _connect(client, "Bob")
        deck = _legal_deck(decks)
        gid = client.post("/api/multiplayer/games", json={"playerId": ann}).json()["game"]["id"]
        client.post(f"/api/multiplayer/games/{gid}/join", json={"playerId": bob})
        client.post(
            f"/api/multiplayer/games/{gid}/options", json={"playerId": ann, "gameFormat": "archenemy"}
        )
        for pid in (ann, bob):
            client.post(f"/api/multiplayer/games/{gid}/deck", json={"playerId": pid, "deckId": deck.id})
        for pid in (ann, bob):
            client.post(f"/api/multiplayer/games/{gid}/ready", json={"playerId": pid})
        body = client.post(f"/api/multiplayer/games/{gid}/start", json={"playerId": ann}).json()
        assert body["view"]["state"]["archenemy_id"] == ann  # Ann is the host


class TestBannerColors:
    """A seat's cosmetic banner colour (`Seat.banner_color`, UC4 Setup)."""

    def test_normalizes_to_wubrg_order(self):
        assert normalize_banner_color("uw") == "wu"
        assert normalize_banner_color("GRB") == "brg"
        assert normalize_banner_color("wwww") == "w"
        # Nothing recognizable left is the grey colourless banner, and an
        # unset colour stays unset (rather than becoming grey).
        assert normalize_banner_color("xyz") == "c"
        assert normalize_banner_color("") == "c"
        assert normalize_banner_color(None) is None

    def test_setting_a_colour_does_not_clear_acceptance(self, env):
        client = env["client"]
        gid, ann, _bob = _seated_game(env)  # both already accepted
        body = client.post(
            f"/api/multiplayer/games/{gid}/banner", json={"playerId": ann, "color": "UW"}
        ).json()
        seats = {s["player_id"]: s for s in body["game"]["seats"]}
        assert seats[ann]["banner_color"] == "wu"
        # Repainting a banner isn't a change to the *game* anyone accepted.
        assert all(s["ready"] for s in body["game"]["seats"])
        assert body["game"]["all_ready"] is True

    def test_deck_colour_identity_is_the_default_banner(self, env):
        client, decks = env["client"], env["decks"]
        ann = _connect(client, "Ann")
        deck = _legal_deck(decks, color_identity=["G", "U"])
        gid = client.post("/api/multiplayer/games", json={"playerId": ann}).json()["game"]["id"]
        body = client.post(
            f"/api/multiplayer/games/{gid}/deck", json={"playerId": ann, "deckId": deck.id}
        ).json()
        assert body["game"]["seats"][0]["banner_color"] == "ug"

    def test_an_explicit_colour_survives_a_deck_change(self, env):
        client, decks = env["client"], env["decks"]
        ann = _connect(client, "Ann")
        gid = client.post("/api/multiplayer/games", json={"playerId": ann}).json()["game"]["id"]
        client.post(f"/api/multiplayer/games/{gid}/banner", json={"playerId": ann, "color": "r"})
        deck = _legal_deck(decks, color_identity=["G"])
        body = client.post(
            f"/api/multiplayer/games/{gid}/deck", json={"playerId": ann, "deckId": deck.id}
        ).json()
        assert body["game"]["seats"][0]["banner_color"] == "r"

    def test_an_uncomputed_identity_leaves_the_seat_unpainted(self, env):
        client, decks = env["client"], env["decks"]
        ann = _connect(client, "Ann")
        deck = _legal_deck(decks)  # colour identity not computed yet
        gid = client.post("/api/multiplayer/games", json={"playerId": ann}).json()["game"]["id"]
        body = client.post(
            f"/api/multiplayer/games/{gid}/deck", json={"playerId": ann, "deckId": deck.id}
        ).json()
        assert body["game"]["seats"][0]["banner_color"] is None

    def test_you_cannot_paint_someone_elses_seat(self, env):
        client = env["client"]
        gid, ann, bob = _seated_game(env)
        response = client.post(
            f"/api/multiplayer/games/{gid}/banner",
            json={"playerId": ann, "color": "b", "seatId": bob},
        )
        assert response.status_code == 400
        seats = {s["player_id"]: s for s in env["lobby"].game(gid).to_dict()["seats"]}
        assert seats[bob]["banner_color"] is None

    def test_the_host_paints_a_bot_seat(self, env):
        client = env["client"]
        ann = _connect(client, "Ann")
        gid = client.post("/api/multiplayer/games", json={"playerId": ann}).json()["game"]["id"]
        body = client.post(
            f"/api/multiplayer/games/{gid}/bots", json={"playerId": ann, "kind": "goldfish"}
        ).json()
        bot_id = next(s["player_id"] for s in body["game"]["seats"] if s["is_bot"])
        body = client.post(
            f"/api/multiplayer/games/{gid}/banner",
            json={"playerId": ann, "color": "wbg", "seatId": bot_id},
        ).json()
        seats = {s["player_id"]: s for s in body["game"]["seats"]}
        assert seats[bot_id]["banner_color"] == "wbg"


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
        decks.save_global(bad)
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
        assert before["priority"] == {
            "interactive": True,
            "player_id": ann,
            "passed": [],
            "timer_seconds": 20,
            "yields": {},
            "stops": {},
            "next_step": "draw",
        }

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

    def test_leaving_a_finished_game_closes_the_table(self, env):
        """The end of a match is when a table should stop existing.

        A *running* game keeps the seat of someone who walks away — they
        may come back to the position. A finished one has no position left
        to come back to, so leaving it really leaves, and the last player
        out takes the table with them instead of littering everyone's
        lobby with a dead row.
        """
        client = env["client"]
        gid, ann, bob = _seated_game(env)
        client.post(f"/api/multiplayer/games/{gid}/start", json={"playerId": ann})
        client.post(f"/api/multiplayer/games/{gid}/concede", json={"playerId": bob})

        first = client.post(f"/api/multiplayer/games/{gid}/leave", json={"playerId": bob}).json()
        assert [s["player_id"] for s in first["game"]["seats"]] == [ann]
        last = client.post(f"/api/multiplayer/games/{gid}/leave", json={"playerId": ann}).json()
        assert last["game"] is None
        assert last["lobby"]["games"] == []

    def test_leaving_a_running_game_keeps_the_seat(self, env):
        client = env["client"]
        gid, ann, bob = _seated_game(env)
        client.post(f"/api/multiplayer/games/{gid}/start", json={"playerId": ann})
        body = client.post(f"/api/multiplayer/games/{gid}/leave", json={"playerId": bob}).json()
        assert [s["player_id"] for s in body["game"]["seats"]] == [ann, bob]


def _seated_game_with_takebacks(env, count):
    """Like `_seated_game`, but the host configures a take-back budget first.

    Options first, decks+ready after — changing the table (`set_options`)
    clears every seat's acceptance, so it has to happen before anyone
    accepts, the same ordering `_seated_game`'s own comment calls out for
    picking a deck.
    """
    client, decks = env["client"], env["decks"]
    ann, bob = _connect(client, "Ann"), _connect(client, "Bob")
    deck = _legal_deck(decks)
    game_id = client.post(
        "/api/multiplayer/games", json={"playerId": ann, "name": "Testtisch"}
    ).json()["game"]["id"]
    client.post(f"/api/multiplayer/games/{game_id}/join", json={"playerId": bob})
    client.post(
        f"/api/multiplayer/games/{game_id}/options",
        json={"playerId": ann, "takebacksPerPlayer": count},
    )
    for pid in (ann, bob):
        client.post(
            f"/api/multiplayer/games/{game_id}/deck", json={"playerId": pid, "deckId": deck.id}
        )
    for pid in (ann, bob):
        client.post(f"/api/multiplayer/games/{game_id}/ready", json={"playerId": pid})
    return game_id, ann, bob


class TestPodSizedTables:
    """A table of three or four through the HTTP routes (`MAX_SEATS` = 4).

    The engine and seat machinery are covered in `test_multiplayer_pods.py`;
    what's checked here is that a pod can actually be *opened, filled and
    started* over the API — including the host resizing the table and the
    seat cap being enforced by the route rather than only by the lobby.
    """

    def _pod(self, env, size=4):
        client, decks = env["client"], env["decks"]
        names = ["Ann", "Bob", "Cid", "Dot"][:size]
        ids = [_connect(client, name) for name in names]
        deck = _legal_deck(decks)
        gid = client.post(
            "/api/multiplayer/games", json={"playerId": ids[0], "numPlayers": size}
        ).json()["game"]["id"]
        for pid in ids[1:]:
            client.post(f"/api/multiplayer/games/{gid}/join", json={"playerId": pid})
        for pid in ids:
            client.post(
                f"/api/multiplayer/games/{gid}/deck", json={"playerId": pid, "deckId": deck.id}
            )
        for pid in ids:
            client.post(f"/api/multiplayer/games/{gid}/ready", json={"playerId": pid})
        return gid, ids

    def test_a_four_seat_table_starts_and_deals_four_hands(self, env):
        client = env["client"]
        gid, ids = self._pod(env)
        body = client.post(
            f"/api/multiplayer/games/{gid}/start", json={"playerId": ids[0]}
        ).json()
        assert body["game"]["status"] == "running"
        view = body["view"]
        hands = {p["id"]: p["hand_count"] for p in view["state"]["players"]}
        assert hands == {pid: 7 for pid in ids}
        # RULE 400.2 with three opponents: only the caller's own hand is sent.
        sent = {p["id"]: len(p["hand"]) for p in view["state"]["players"]}
        assert sent == {ids[0]: 7, ids[1]: 0, ids[2]: 0, ids[3]: 0}

    def test_a_three_seat_table_starts_too(self, env):
        client = env["client"]
        gid, ids = self._pod(env, size=3)
        body = client.post(
            f"/api/multiplayer/games/{gid}/start", json={"playerId": ids[0]}
        ).json()
        assert body["game"]["num_players"] == 3
        assert len(body["view"]["state"]["players"]) == 3

    def test_the_host_can_grow_the_table_before_it_starts(self, env):
        client = env["client"]
        ann = _connect(client, "Ann")
        gid = client.post("/api/multiplayer/games", json={"playerId": ann}).json()["game"]["id"]
        body = client.post(
            f"/api/multiplayer/games/{gid}/options", json={"playerId": ann, "numPlayers": 4}
        ).json()
        assert body["game"]["num_players"] == 4

    def test_asking_for_more_than_four_seats_is_capped(self, env):
        client = env["client"]
        ann = _connect(client, "Ann")
        body = client.post(
            "/api/multiplayer/games", json={"playerId": ann, "numPlayers": 8}
        ).json()
        assert body["game"]["num_players"] == 4

    def test_a_fifth_player_cannot_join_a_full_pod(self, env):
        client = env["client"]
        gid, _ids = self._pod(env)
        eve = _connect(client, "Eve")
        assert (
            client.post(f"/api/multiplayer/games/{gid}/join", json={"playerId": eve}).status_code
            == 400
        )


class TestTakeBack:
    """UC4 Setup's per-seat undo budget through the HTTP API.

    The engine-level behaviour (finding the right history point, the
    shared-timeline trade-off, the budget bookkeeping) is exercised
    thoroughly in `test_multiplayer_session.py::TestTakeBack`; this class
    only checks the parts that only exist at the API layer: the route
    itself, that it survives despite the caller not holding priority, and
    that an observer/non-seat can't call it.
    """

    def _start_and_keep(self, env, gid, ann, bob):
        """Start, keep both hands, and pass through to Ann's main1 — the
        only step besides main2 offering `play_land` at all."""
        client = env["client"]
        client.post(f"/api/multiplayer/games/{gid}/start", json={"playerId": ann})
        for pid in (ann, bob):
            client.post(
                f"/api/multiplayer/games/{gid}/action",
                json={"playerId": pid, "action": {"type": "keep_hand", "bottom_instance_ids": []}},
            )
        for _ in range(20):
            view = client.get(
                f"/api/multiplayer/games/{gid}", params={"player_id": ann}
            ).json()["view"]
            if view["state"]["current_step"] == "main1":
                return
            holder = view["priority"]["player_id"]
            client.post(
                f"/api/multiplayer/games/{gid}/action",
                json={"playerId": holder, "action": {"type": "pass_priority"}},
            )
        raise AssertionError("never reached main1")

    def test_takes_back_the_callers_own_last_move(self, env):
        client = env["client"]
        gid, ann, bob = _seated_game_with_takebacks(env, 1)
        self._start_and_keep(env, gid, ann, bob)
        view = client.get(f"/api/multiplayer/games/{gid}", params={"player_id": ann}).json()["view"]
        assert view["takebacks_remaining"] == {ann: 1, bob: 1}

        land_action = next(a for a in view["legal_actions"] if a["type"] == "play_land")
        before = client.post(
            f"/api/multiplayer/games/{gid}/action",
            json={"playerId": ann, "action": land_action},
        ).json()
        assert any(
            o["controller_id"] == ann for o in before["view"]["state"]["battlefield"]
        )

        body = client.post(
            f"/api/multiplayer/games/{gid}/takeback", json={"playerId": ann}
        ).json()
        assert not any(
            o["controller_id"] == ann for o in body["view"]["state"]["battlefield"]
        )
        assert body["view"]["takebacks_remaining"] == {ann: 0, bob: 1}

    def test_works_even_without_priority(self, env):
        # Not routed through the RULE 117 dispatch gate at all — the same
        # exemption `concede` gets, since a misclick doesn't wait for a
        # convenient moment to be noticed.
        client = env["client"]
        gid, ann, bob = _seated_game_with_takebacks(env, 1)
        self._start_and_keep(env, gid, ann, bob)
        client.post(
            f"/api/multiplayer/games/{gid}/action",
            json={"playerId": ann, "action": {"type": "pass_priority"}},
        )
        view = client.get(f"/api/multiplayer/games/{gid}", params={"player_id": bob}).json()["view"]
        assert view["priority"]["player_id"] == bob  # not ann's priority window

        response = client.post(f"/api/multiplayer/games/{gid}/takeback", json={"playerId": ann})
        assert response.status_code == 200

    def test_no_budget_configured_is_a_400(self, env):
        client = env["client"]
        gid, ann, bob = _seated_game(env)  # default: no take-backs configured
        self._start_and_keep(env, gid, ann, bob)
        response = client.post(f"/api/multiplayer/games/{gid}/takeback", json={"playerId": ann})
        assert response.status_code == 400

    def test_an_observer_cannot_take_back_anything(self, env):
        client = env["client"]
        gid, ann, bob = _seated_game_with_takebacks(env, 1)
        self._start_and_keep(env, gid, ann, bob)
        watcher = _connect(client, "Watcher")
        client.post(f"/api/multiplayer/games/{gid}/observe", json={"playerId": watcher})
        response = client.post(
            f"/api/multiplayer/games/{gid}/takeback", json={"playerId": watcher}
        )
        assert response.status_code == 403


class TestBots:
    """Seating a bot (UC5) — `services/bots.py` through the lobby routes.

    The bot-specific part of the API is small on purpose: a bot seat is an
    ordinary seat whose occupant has no client, so everything here is about
    the two things that follow from that — the host acts *for* it (deck
    pick, removal), and the server plays it (keeping, taking its turn)
    without anybody clicking anything.
    """

    def _table_with_a_bot(self, env, kind="greedy"):
        """Ann + one bot, both decks picked, Ann accepted. Not started."""
        client, decks = env["client"], env["decks"]
        ann = _connect(client, "Ann")
        deck = _legal_deck(decks)
        gid = client.post("/api/multiplayer/games", json={"playerId": ann}).json()["game"]["id"]
        body = client.post(
            f"/api/multiplayer/games/{gid}/bots", json={"playerId": ann, "kind": kind}
        ).json()
        bot_id = body["game"]["seats"][1]["player_id"]
        for pid, seat in ((ann, None), (ann, bot_id)):
            payload = {"playerId": pid, "deckId": deck.id}
            if seat:
                payload["seatId"] = seat
            client.post(f"/api/multiplayer/games/{gid}/deck", json=payload)
        client.post(f"/api/multiplayer/games/{gid}/ready", json={"playerId": ann})
        return gid, ann, bot_id

    def test_the_catalogue_lists_every_bot_kind(self, env):
        bots = env["client"].get("/api/multiplayer/bots").json()["bots"]
        kinds = {b["kind"]: b for b in bots}
        assert set(kinds) == {"goldfish", "greedy", "smart", "smart2", "mana_maximizer", "mcp"}
        assert kinds["goldfish"]["label"] and kinds["goldfish"]["description"]

    def test_the_host_can_seat_a_bot(self, env):
        client = env["client"]
        ann = _connect(client, "Ann")
        gid = client.post("/api/multiplayer/games", json={"playerId": ann}).json()["game"]["id"]
        body = client.post(
            f"/api/multiplayer/games/{gid}/bots", json={"playerId": ann, "kind": "goldfish"}
        ).json()
        seat = body["game"]["seats"][1]
        assert seat["is_bot"] is True
        assert seat["bot_kind"] == "goldfish"
        assert seat["name"] == "Goldfisch-Bot"
        # No deck yet, so the table still isn't ready to start.
        assert seat["ready"] is False

    def test_a_bot_is_not_a_lobby_player(self, env):
        """It has a `LobbyPlayer` internally, but it's nobody to play against."""
        client = env["client"]
        ann = _connect(client, "Ann")
        gid = client.post("/api/multiplayer/games", json={"playerId": ann}).json()["game"]["id"]
        body = client.post(
            f"/api/multiplayer/games/{gid}/bots", json={"playerId": ann, "kind": "greedy"}
        ).json()
        assert [p["id"] for p in body["lobby"]["players"]] == [ann]

    def test_only_the_host_can_seat_or_remove_a_bot(self, env):
        client = env["client"]
        ann, bob = _connect(client, "Ann"), _connect(client, "Bob")
        gid = client.post("/api/multiplayer/games", json={"playerId": ann}).json()["game"]["id"]
        client.post(f"/api/multiplayer/games/{gid}/join", json={"playerId": bob})
        response = client.post(
            f"/api/multiplayer/games/{gid}/bots", json={"playerId": bob, "kind": "greedy"}
        )
        assert response.status_code == 400

    def test_an_unknown_bot_kind_is_refused(self, env):
        client = env["client"]
        ann = _connect(client, "Ann")
        gid = client.post("/api/multiplayer/games", json={"playerId": ann}).json()["game"]["id"]
        response = client.post(
            f"/api/multiplayer/games/{gid}/bots", json={"playerId": ann, "kind": "kasparov"}
        )
        assert response.status_code == 400
        assert len(env["lobby"].game(gid).seats) == 1

    def test_the_host_picks_the_bot_s_deck_and_the_seat_goes_ready(self, env):
        gid, ann, bot_id = self._table_with_a_bot(env)
        game = (
            env["client"]
            .get(f"/api/multiplayer/games/{gid}", params={"player_id": ann})
            .json()["game"]
        )
        seat = next(s for s in game["seats"] if s["player_id"] == bot_id)
        assert seat["deck_name"] == "Mono-G"
        # A bot with a deck counts as accepted — it has no client to accept.
        assert seat["ready"] is True

    def test_the_host_can_take_a_bot_back_off_the_table(self, env):
        client = env["client"]
        gid, ann, bot_id = self._table_with_a_bot(env)
        body = client.post(
            f"/api/multiplayer/games/{gid}/bots/remove", json={"playerId": ann, "botId": bot_id}
        ).json()
        assert [s["player_id"] for s in body["game"]["seats"]] == [ann]

    def test_the_host_cannot_pick_a_deck_for_another_human(self, env):
        """`seatId` is for bot seats only — not a way to pick for a person.

        (`Lobby.set_deck`'s companion "only the host" guard can't be
        reached from a two-seat table — a host plus a bot fills it, so
        there is never a non-host sitting next to a bot. It's there for
        when more seats exist.)
        """
        client, decks = env["client"], env["decks"]
        ann, bob = _connect(client, "Ann"), _connect(client, "Bob")
        deck = _legal_deck(decks)
        gid = client.post("/api/multiplayer/games", json={"playerId": ann}).json()["game"]["id"]
        client.post(f"/api/multiplayer/games/{gid}/join", json={"playerId": bob})
        response = client.post(
            f"/api/multiplayer/games/{gid}/deck",
            json={"playerId": ann, "deckId": deck.id, "seatId": bob},
        )
        assert response.status_code == 400

    def test_a_human_seat_cannot_be_removed_as_a_bot(self, env):
        client = env["client"]
        gid, ann, _bot_id = self._table_with_a_bot(env)
        response = client.post(
            f"/api/multiplayer/games/{gid}/bots/remove", json={"playerId": ann, "botId": ann}
        )
        assert response.status_code == 400

    def test_starting_keeps_the_bot_s_hand_for_it(self, env):
        """RULE 103.4 — nobody is going to click "Behalten" for the bot."""
        client = env["client"]
        gid, ann, bot_id = self._table_with_a_bot(env)
        body = client.post(f"/api/multiplayer/games/{gid}/start", json={"playerId": ann}).json()
        setup = body["view"]["setup"]
        assert setup["complete"] is False  # Ann still has to keep
        assert setup["waiting_for"] == [ann]  # ... and only Ann

    def test_the_greedy_bot_takes_its_turn_without_a_client(self, env):
        client = env["client"]
        gid, ann, bot_id = self._table_with_a_bot(env, kind="greedy")
        client.post(f"/api/multiplayer/games/{gid}/start", json={"playerId": ann})
        body = client.post(
            f"/api/multiplayer/games/{gid}/action",
            json={"playerId": ann, "action": {"type": "keep_hand", "bottom_instance_ids": []}},
        ).json()
        # Ann (seat 1) is on the play, so the bot's whole turn is turn 2 and
        # happens inside the responses to Ann's own passes.
        view = body["view"]
        assert view["setup"]["complete"] is True
        for _ in range(40):
            if view["state"]["internal_turn"]["number"] > 2:
                break
            view = client.post(
                f"/api/multiplayer/games/{gid}/action",
                json={"playerId": ann, "action": {"type": "pass_priority"}},
            ).json()["view"]
        names = {obj["name"] for obj in _battlefield_of(view, bot_id)}
        # Greedy, so: the land *and* everything the land can pay for — here
        # the commander out of the command zone.
        assert "Forest" in names, "the bot never played a land"
        assert "Test Commander" in names, "the bot never cast anything"

    def test_the_goldfish_bot_only_ever_plays_lands(self, env):
        client = env["client"]
        gid, ann, bot_id = self._table_with_a_bot(env, kind="goldfish")
        client.post(f"/api/multiplayer/games/{gid}/start", json={"playerId": ann})
        view = client.post(
            f"/api/multiplayer/games/{gid}/action",
            json={"playerId": ann, "action": {"type": "keep_hand", "bottom_instance_ids": []}},
        ).json()["view"]
        for _ in range(60):
            if view["state"]["internal_turn"]["number"] > 2:
                break
            view = client.post(
                f"/api/multiplayer/games/{gid}/action",
                json={"playerId": ann, "action": {"type": "pass_priority"}},
            ).json()["view"]
        battlefield = _battlefield_of(view, bot_id)
        assert battlefield, "the goldfish never played a land"
        assert all("Land" in obj["type_line"] for obj in battlefield)


class TestLobbyWebSocket:
    def test_connecting_registers_the_player_and_returns_an_id(self, env):
        client = env["client"]
        with lobby_socket(client, "Ann") as (socket, welcome):
            assert welcome["type"] == "welcome"
            assert welcome["player_id"]
            assert welcome["tab_id"]
            assert "secret" not in welcome
            assert [p["name"] for p in welcome["lobby"]["players"]] == ["Ann"]

    def test_presence_reports_available_and_broadcasts(self, env):
        client = env["client"]
        with lobby_socket(client, "Ann") as (socket, welcome):
            _drain_until(socket, "lobby_update")  # the connect broadcasts
            socket.send_json({"type": "presence", "state": AVAILABLE})
            update = _drain_until(socket, "lobby_update")
            assert update["lobby"]["players"][0]["state"] == AVAILABLE
            assert env["lobby"].player(welcome["player_id"]).state == AVAILABLE

    def test_a_player_in_a_game_stays_playing(self, env):
        client = env["client"]
        with lobby_socket(client, "Ann") as (socket, welcome):
            player_id = welcome["player_id"]
            client.post("/api/multiplayer/games", json={"playerId": player_id})
            # Even if the client claims to be idling in the lobby, holding a
            # seat is what decides the state.
            env["lobby"].set_presence(player_id, AVAILABLE)
            assert env["lobby"].player(player_id).state == PLAYING

    def test_disconnecting_removes_the_player(self, env):
        client = env["client"]
        with lobby_socket(client, "Ann"):
            pass
        assert client.get("/api/multiplayer/lobby").json()["players"] == []

    def test_a_move_is_pushed_to_both_seats_with_their_own_view(self, env):
        client = env["client"]
        with lobby_socket(client, "Ann") as (ann_socket, ann_welcome):
            ann = ann_welcome["player_id"]
            with lobby_socket(client, "Bob") as (bob_socket, bob_welcome):
                bob = bob_welcome["player_id"]
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
    """A seat is held by *account* (PLR-9c), so a reload doesn't cost you the game."""

    def test_reconnecting_as_the_same_account_reclaims_the_seat(self, env):
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

        # … and the same account comes back to the same seat, same game.
        again = client.post("/api/multiplayer/connect", json={"name": "Ann"}).json()["player"]
        assert again["id"] == ann
        assert again["connected"] is True
        assert again["game_id"] == gid

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

    def test_a_ping_also_resets_the_idle_timer(self, env):
        # PLR-5: a `ping` over `/ws/lobby` is liveness too, not just a real
        # game action — the whole point is to remove the flicker of a
        # player who is genuinely still there but just thinking a move
        # over.
        client = env["client"]
        _gid, ann, _bob = self._running(env)
        before = env["lobby"].player(ann).last_action_at

        import time

        time.sleep(0.01)
        with lobby_socket(client, "Ann") as (socket, welcome):
            assert welcome["player_id"] == ann  # the account's own seat
            socket.send_json({"type": "ping"})
            pong = _drain_until(socket, "pong")
            assert pong == {"type": "pong"}
        assert env["lobby"].player(ann).last_action_at > before


class TestMcpSeat:
    """PLR-16: a seat an external MCP client plays through its seat token."""

    def _table(self, env):
        client, decks = env["client"], env["decks"]
        ann = _connect(client, "Ann")
        deck = _legal_deck(decks)
        gid = client.post("/api/multiplayer/games", json={"playerId": ann}).json()["game"]["id"]
        body = client.post(
            f"/api/multiplayer/games/{gid}/bots", json={"playerId": ann, "kind": "mcp"}
        ).json()
        seat_id = body["game"]["seats"][1]["player_id"]
        for seat in (None, seat_id):
            payload = {"playerId": ann, "deckId": deck.id}
            if seat:
                payload["seatId"] = seat
            client.post(f"/api/multiplayer/games/{gid}/deck", json=payload)
        client.post(f"/api/multiplayer/games/{gid}/ready", json={"playerId": ann})
        token = client.post(
            f"/api/multiplayer/games/{gid}/bots/token", json={"playerId": ann, "botId": seat_id}
        ).json()["seat_token"]
        return gid, ann, seat_id, token, {"Authorization": f"Bearer {token}"}

    def test_token_is_never_in_the_public_snapshot(self, env):
        gid, ann, seat_id, token, _ = self._table(env)
        assert token not in str(env["client"].get("/api/multiplayer/lobby").json())
        assert token not in str(env["client"].get(f"/api/multiplayer/games/{gid}?player_id={ann}").json())

    def test_token_comes_with_a_launch_hint_that_resolves_the_adapter(self, env):
        from pathlib import Path

        client = env["client"]
        gid, ann, seat_id, token, _ = self._table(env)
        body = client.post(
            f"/api/multiplayer/games/{gid}/bots/token", json={"playerId": ann, "botId": seat_id}
        ).json()
        assert body["seat_token"] == token
        # The adapter is only importable from `backend/`, which the MCP client
        # does not run in, so the hint has to name that directory.
        assert (Path(body["backend_dir"]) / "mtg_mcp" / "__main__.py").is_file()
        assert Path(body["python"]).is_file()

    def test_only_the_host_can_read_the_token(self, env):
        client = env["client"]
        gid, ann, seat_id, _, _ = self._table(env)
        bob = _connect(client, "Bob")
        response = client.post(
            f"/api/multiplayer/games/{gid}/bots/token", json={"playerId": bob, "botId": seat_id}
        )
        assert response.status_code == 400

    def test_seat_is_not_ready_until_the_client_connects(self, env):
        client = env["client"]
        gid, ann, seat_id, _, headers = self._table(env)
        game = client.get(f"/api/multiplayer/games/{gid}?player_id={ann}").json()["game"]
        assert game["seats"][1]["ready"] is False
        assert game["seats"][1]["mcp_connected"] is False
        assert client.get("/api/mcp-seat/view", headers=headers).status_code == 200
        game = client.get(f"/api/multiplayer/games/{gid}?player_id={ann}").json()["game"]
        assert game["seats"][1]["ready"] is True
        assert game["seats"][1]["mcp_connected"] is True

    def test_a_wrong_or_missing_token_is_rejected(self, env):
        client = env["client"]
        self._table(env)
        assert client.get("/api/mcp-seat/view").status_code == 401
        assert client.get("/api/mcp-seat/view", headers={"Authorization": "Bearer nope"}).status_code == 401

    def test_client_plays_its_own_seat_and_cannot_act_out_of_turn(self, env):
        client = env["client"]
        gid, ann, seat_id, _, headers = self._table(env)
        client.get("/api/mcp-seat/view", headers=headers)
        client.post(f"/api/multiplayer/games/{gid}/ready", json={"playerId": ann})
        started = client.post(f"/api/multiplayer/games/{gid}/start", json={"playerId": ann})
        assert started.status_code == 200
        view = client.get("/api/mcp-seat/view", headers=headers).json()
        assert view["seat_id"] == seat_id
        # Opponent hand stays hidden from the MCP seat (RULE 400.2).
        assert view["view"] is not None
        waited = client.get("/api/mcp-seat/wait?timeout=0", headers=headers).json()
        assert "timed_out" in waited
        rejected = client.post(
            "/api/mcp-seat/action", headers=headers, json={"action": {"type": "no_such_action"}}
        )
        assert rejected.status_code == 400

    def test_a_silent_client_is_replaced_by_smart_bot(self, env):
        from mtg_analyzer.services.bots import bots_for_game

        gid, ann, seat_id, _, headers = self._table(env)
        env["client"].get("/api/mcp-seat/view", headers=headers)
        game = env["lobby"].game(gid)
        assert [b.kind for b in bots_for_game(game).values()] == ["mcp"]
        game.seats[1].mcp_last_seen = None  # the client went away
        assert [b.kind for b in bots_for_game(game).values()] == ["smart"]

    def test_action_and_concede_responses_carry_the_seat_id(self, env):
        client = env["client"]
        gid, ann, seat_id, _, headers = self._table(env)
        client.get("/api/mcp-seat/view", headers=headers)
        client.post(f"/api/multiplayer/games/{gid}/ready", json={"playerId": ann})
        client.post(f"/api/multiplayer/games/{gid}/start", json={"playerId": ann})
        view = client.get("/api/mcp-seat/view", headers=headers).json()["view"]
        action = (view.get("legal_actions") or [None])[0]
        if action is not None:
            response = client.post("/api/mcp-seat/action", headers=headers, json={"action": action})
            assert response.status_code == 200
            assert response.json()["seat_id"] == seat_id
        conceded = client.post("/api/mcp-seat/concede", headers=headers)
        assert conceded.status_code == 200
        assert conceded.json()["seat_id"] == seat_id

    def test_client_can_name_its_seat_in_setup_only(self, env):
        client = env["client"]
        gid, ann, seat_id, _, headers = self._table(env)
        named = client.post("/api/mcp-seat/name", headers=headers, json={"name": "  Claude   Opus "})
        assert named.status_code == 200 and named.json()["name"] == "Claude Opus"
        game = client.get(f"/api/multiplayer/games/{gid}?player_id={ann}").json()["game"]
        assert game["seats"][1]["name"] == "Claude Opus"
        assert client.post("/api/mcp-seat/name", headers=headers, json={"name": "  "}).status_code == 409
        long_name = client.post("/api/mcp-seat/name", headers=headers, json={"name": "x" * 500}).json()["name"]
        assert len(long_name) == 40
        client.get("/api/mcp-seat/view", headers=headers)
        client.post(f"/api/multiplayer/games/{gid}/ready", json={"playerId": ann})
        client.post(f"/api/multiplayer/games/{gid}/start", json={"playerId": ann})
        assert client.post("/api/mcp-seat/name", headers=headers, json={"name": "Late"}).status_code == 409

    def test_client_reads_its_own_decklist_and_needs_the_token(self, env):
        client = env["client"]
        gid, ann, seat_id, _, headers = self._table(env)
        deck = client.get("/api/mcp-seat/deck", headers=headers)
        assert deck.status_code == 200
        body = deck.json()
        assert "Test Commander" in body["commander"] and "99 Forest" in body["mainboard"]
        assert client.get("/api/mcp-seat/deck").status_code == 401

    def test_client_deck_comes_from_the_seat_snapshot_not_the_deck_store(self, env):
        # PLR-9b: an MCP client holds only a seat token and must not reach the deck store.
        client = env["client"]
        gid, ann, seat_id, _, headers = self._table(env)
        for deck in env["decks"].list_decks(TEST_PLAYER_UUID):
            env["decks"]._connection.execute("DELETE FROM decks WHERE id = ?", (deck.id,))
        body = client.get("/api/mcp-seat/deck", headers=headers).json()
        assert "99 Forest" in body["mainboard"]


    def test_non_ascii_and_revoked_mcp_tokens_are_rejected(self, env):
        gid, host, seat_id, token, headers = self._table(env)
        assert env['lobby'].seat_for_token('🤖') is None
        removed = env['client'].post(f'/api/multiplayer/games/{gid}/bots/remove',
                                     json={'playerId': host, 'botId': seat_id})
        assert removed.status_code == 200
        assert env['client'].get('/api/mcp-seat/view', headers=headers).status_code == 401


def test_mcp_server_credential_rotation_and_seat_are_both_required(env):
    client = env['client']
    _, _, _, seat_token, headers = TestMcpSeat()._table(env)
    assert client.get('/api/mcp-seat/view', headers=headers).status_code == 200
    assert client.get('/api/mcp-seat/view', headers={**headers, 'X-MCP-Server-Token': 'wrong'}).status_code == 401
    assert client.get('/api/mcp-seat/view', headers={'Authorization': 'Bearer invalid'}).status_code == 401
    rotated = client.post('/api/mcp-settings/rotate').json()['server_token']
    assert rotated != env['mcp_server_token']
    assert client.get('/api/mcp-seat/view', headers=headers).status_code == 401
    assert client.get('/api/mcp-seat/view', headers={**headers, 'X-MCP-Server-Token': rotated}).status_code == 200
    assert seat_token not in str(client.get('/api/mcp-settings').json())
    assert rotated not in str(client.get('/api/mcp-settings').json())


class TestSessionIsolationBug38:
    """BUG-38: a lobby table's `session_id` is public, so the goldfish/solo
    REST surfaces must not address it; only the seat-checked routes may."""

    def _running(self, env):
        client = env["client"]
        gid, ann, bob = _seated_game(env)
        body = client.post(f"/api/multiplayer/games/{gid}/start", json={"playerId": ann}).json()
        return gid, ann, bob, body["game"]["session_id"]

    def test_goldfish_routes_404_for_a_lobby_table_and_leak_nothing(self, env):
        client = env["client"]
        _gid, ann, _bob, sid = self._running(env)
        responses = [
            client.get(f"/api/game/{sid}"),
            client.get(f"/api/game/{sid}/replay-export"),
            client.post(f"/api/game/{sid}/ui-draft", json={"playerId": ann, "draft": None}),
            client.post(f"/api/game/{sid}/action", json={"type": "pass_priority"}),
            client.post(f"/api/game/{sid}/rewind", json={"steps": 1}),
            client.post(f"/api/game/{sid}/restart", json={}),
            client.delete(f"/api/game/{sid}"),
        ]
        for res in responses:
            assert res.status_code == 404
            assert "hand" not in res.text
        assert env["sessions"].get(sid)  # still alive, DELETE did not remove it

    def test_solo_routes_404_for_a_lobby_table(self, env):
        client = env["client"]
        _gid, _ann, _bob, sid = self._running(env)
        for res in (
            client.get(f"/api/solo/{sid}"),
            client.post(f"/api/solo/{sid}/action", json={"type": "pass_priority"}),
            client.post(f"/api/solo/{sid}/concede", json={}),
            client.post(f"/api/solo/{sid}/restart", json={}),
            client.delete(f"/api/solo/{sid}"),
            client.post(f"/api/solo/{sid}/ui-draft", json={"draft": None}),
            client.get(f"/api/solo/{sid}/replay-export"),
        ):
            assert res.status_code == 404
            assert "hand" not in res.text
        assert env["sessions"].get(sid)

    def test_solo_routes_404_for_a_goldfish_session(self, env):
        sid = env["sessions"].create_replay(
            __import__("mtg_analyzer.services.replay", fromlist=["x"]).blank_replay(2), loader=None
        ).id
        assert env["client"].get(f"/api/solo/{sid}").status_code == 404
        assert env["client"].delete(f"/api/solo/{sid}").status_code == 404
        assert env["sessions"].get(sid)

    def test_no_game_websocket_remains(self, env):
        from starlette.websockets import WebSocketDisconnect

        with pytest.raises(WebSocketDisconnect):
            with env["client"].websocket_connect("/ws/game/anything"):
                pass

    def test_replay_export_needs_a_seat_and_a_finished_game(self, env):
        client = env["client"]
        gid, ann, bob, sid = self._running(env)
        url = f"/api/multiplayer/games/{gid}/replay-export"
        assert client.get(url, params={"player_id": ann}).status_code == 409  # mid-game
        stranger = _connect(client, "Cy")
        assert client.get(url, params={"player_id": stranger}).status_code == 403
        env["sessions"].get(sid).engine.state.game_over = True
        res = client.get(url, params={"player_id": ann})
        assert res.status_code == 200
        assert client.get(url, params={"player_id": stranger}).status_code == 403

    def test_ui_draft_is_seat_checked(self, env):
        client = env["client"]
        gid, ann, _bob, sid = self._running(env)
        url = f"/api/multiplayer/games/{gid}/ui-draft"
        stranger = _connect(client, "Cy")
        assert client.post(url, json={"playerId": stranger, "draft": {"k": 1}}).status_code == 403
        assert client.post(url, json={"playerId": ann, "draft": {"k": 1}}).status_code == 200
        assert env["sessions"].get(sid)._ui_drafts[ann] == {"k": 1}


class TestPlayerOwnershipPlr9c:
    """PLR-9c: lobby/seat ids are public; every request must come from the owning account."""

    def _running(self, env):
        client = env["client"]
        gid, ann, bob = _seated_game(env)
        client.post(f"/api/multiplayer/games/{gid}/start", json={"playerId": ann})
        return gid, ann, bob

    def _calls(self, gid, ann):
        """Every player-guarded route, as (method, url, body-or-params)."""
        base = f"/api/multiplayer/games/{gid}"
        body = {"playerId": ann}
        return [
            ("post", "/api/multiplayer/games", body),
            ("post", f"{base}/join", body),
            ("post", f"{base}/observe", body),
            ("post", f"{base}/leave", body),
            ("post", f"{base}/deck", {**body, "deckId": "x"}),
            ("post", f"{base}/banner", {**body, "color": "R"}),
            ("post", f"{base}/bots", {**body, "kind": "goldfish"}),
            ("post", f"{base}/bots/token", {**body, "botId": "b"}),
            ("post", f"{base}/bots/remove", {**body, "botId": "b"}),
            ("post", f"{base}/options", body),
            ("post", f"{base}/ready", {**body, "ready": True}),
            ("post", f"{base}/start", body),
            ("get", base, {"player_id": ann}),
            ("post", f"{base}/action", {**body, "action": {"type": "pass_priority"}}),
            ("post", f"{base}/concede", body),
            ("post", f"{base}/takeback", body),
            ("post", f"{base}/ui-draft", {**body, "draft": None}),
            ("get", f"{base}/replay-export", {"player_id": ann}),
        ]

    def _send(self, client, method, url, payload, headers):
        if method == "get":
            return client.get(url, params=payload, headers=headers)
        return client.post(url, json=payload, headers=headers)

    def test_every_route_rejects_another_account_naming_the_id(self, env):
        client = env["client"]
        gid, ann, bob = self._running(env)
        for method, url, payload in self._calls(gid, ann):
            for headers in (account_header("Bob"), account_header("Mallory")):
                res = self._send(client, method, url, payload, headers)
                assert res.status_code == 403, (url, headers, res.text)

    def test_the_owning_account_is_accepted(self, env):
        client = env["client"]
        gid, ann, bob = self._running(env)
        headers = account_header("Ann")
        res = client.get(f"/api/multiplayer/games/{gid}", params={"player_id": ann}, headers=headers)
        assert res.status_code == 200
        assert res.json()["view"]["state"]
        res = client.post(
            f"/api/multiplayer/games/{gid}/ui-draft",
            json={"playerId": ann, "draft": {"k": 1}},
            headers=headers,
        )
        assert res.status_code == 200
        res = client.get(
            f"/api/multiplayer/games/{gid}/replay-export", params={"player_id": ann}, headers=headers
        )
        assert res.status_code == 409  # authorized, merely not finished

    def test_foreign_hand_cannot_be_read_or_acted_for(self, env):
        client = env["client"]
        gid, ann, bob = self._running(env)
        url = f"/api/multiplayer/games/{gid}"
        headers = account_header("Bob")  # Bob presents Ann's id
        assert client.get(url, params={"player_id": ann}, headers=headers).status_code == 403
        res = client.post(
            f"{url}/action",
            json={"playerId": ann, "action": {"type": "pass_priority"}},
            headers=headers,
        )
        assert res.status_code == 403

    def test_connect_carries_no_credential_and_snapshots_no_account_id(self, env):
        client = env["client"]
        body = client.post("/api/multiplayer/connect", json={"name": "Ann"}).json()
        assert "secret" not in body
        gid, ann, bob = self._running(env)
        texts = [str(body), client.get("/api/multiplayer/lobby").text, str(env["lobby"].snapshot())]
        texts.append(client.get(f"/api/multiplayer/games/{gid}", params={"player_id": ann}).text)
        for player in env["lobby"].players():
            for text in texts:
                assert player.player_uuid not in text

    def test_legacy_credentials_in_the_connect_body_reclaim_nothing(self, env):
        # Forged client tokens, secrets, ids and names (plan section 8 "Multiplayer").
        client = env["client"]
        victim = client.post("/api/multiplayer/connect", json={"name": "Vic"}).json()["player"]
        mallory = client.post(
            "/api/multiplayer/connect",
            json={"name": "Vic", "playerId": victim["id"], "clientToken": "tok", "secret": "s"},
            headers=account_header("Mallory"),
        ).json()["player"]
        assert mallory["id"] != victim["id"]
        assert mallory["name"] == "Mallory"  # the account name, never the typed one
        assert env["lobby"].player(victim["id"]).name == "Vic"
        assert env["lobby"].player(victim["id"]).connected

    def test_an_unauthenticated_request_is_refused(self, env):
        from mtg_analyzer.api.auth import current_account
        from mtg_analyzer.api.app import app as the_app
        from fastapi import HTTPException

        def nobody():
            raise HTTPException(401, {"code": "unauthenticated"})

        the_app.dependency_overrides[current_account] = nobody
        try:
            assert env["client"].post("/api/multiplayer/connect", json={"name": "Ann"}).status_code == 401
            assert env["client"].get("/api/multiplayer/lobby").status_code == 401
        finally:
            the_app.dependency_overrides.pop(current_account, None)


class TestBugReportTableAccess:
    """BUG-45: a bug report stores every hidden zone, so a lobby table's
    session only yields one to a seated player (the session account owns the seat)."""

    @pytest.fixture
    def report_env(self, env, tmp_path, monkeypatch):
        from mtg_analyzer import config
        monkeypatch.setattr(config, "BUG_REPORT_DIR", tmp_path / "reports")
        gid, ann, bob = _seated_game(env)
        started = env["client"].post(f"/api/multiplayer/games/{gid}/start", json={"playerId": ann}).json()
        watcher = _connect(env["client"], "Watcher")
        env["client"].post(f"/api/multiplayer/games/{gid}/observe", json={"playerId": watcher})
        env["session_id"] = started["game"]["session_id"]
        env.update(ann=ann, bob=bob, watcher=watcher, reports=tmp_path / "reports")
        return env

    def _post(self, env, player_id=None, account=None):
        body = {"description": "bug", "session_id": env["session_id"]}
        if player_id:
            body["player_id"] = player_id
        # A plain client: the injecting one would pick the account itself.
        headers = account_header(account) if account else {}
        return TestClient(app).post("/api/bug-reports", json=body, headers=headers)

    def test_no_identity_is_refused(self, report_env):
        assert self._post(report_env).status_code == 403
        assert not report_env["reports"].exists()

    def test_other_players_account_is_refused(self, report_env):
        assert self._post(report_env, report_env["ann"], "Bob").status_code == 403

    def test_observer_is_refused(self, report_env):
        assert self._post(report_env, report_env["watcher"], "Watcher").status_code == 403

    def test_seated_player_is_stored(self, report_env):
        response = self._post(report_env, report_env["ann"], "Ann")
        assert response.status_code == 201, response.text
        assert (report_env["reports"] / response.json()["filename"]).exists()

    def test_goldfish_session_needs_no_identity(self, report_env):
        goldfish = report_env["sessions"].create_replay  # same non-table path as replay
        from mtg_analyzer.services.replay import blank_replay
        session = goldfish(blank_replay(), loader=None)
        response = TestClient(app).post(
            "/api/bug-reports", json={"description": "bug", "session_id": session.id}
        )
        assert response.status_code == 201
