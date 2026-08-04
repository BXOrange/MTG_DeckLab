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
    decks.save_deck(deck)
    return deck


def _battlefield_of(view, player_id):
    """The permanents ``player_id`` controls (the battlefield is shared)."""
    return [
        obj
        for obj in view["state"]["battlefield"]
        if obj.get("controller_id") == player_id
    ]


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
        assert set(kinds) == {"goldfish", "greedy", "mana_maximizer"}
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
            if view["state"]["turn_number"] > 2:
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
            if view["state"]["turn_number"] > 2:
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
        with client.websocket_connect(f"/ws/lobby?name=Ann&player_id={ann}") as socket:
            socket.receive_json()  # welcome
            socket.send_json({"type": "ping"})
            pong = _drain_until(socket, "pong")
            assert pong == {"type": "pong"}
        assert env["lobby"].player(ann).last_action_at > before
