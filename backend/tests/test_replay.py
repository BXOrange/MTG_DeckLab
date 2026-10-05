"""Tests for Replay / Puzzle mode: descriptor round-trip, edit actions, export.

Reference: mtg_analyzer/services/replay.py, mtg_analyzer/services/game_session.py
(edit_* actions), mtg_analyzer/api/game.py (POST /api/game/replay,
GET /api/game/{id}/replay-export).
"""

from fastapi.testclient import TestClient

from mtg_analyzer.api.app import app
from mtg_analyzer.api.dependencies import (
    get_deck_database,
    get_game_session_manager,
    get_lazy_card_loader,
)
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.services.deck_database import DeckDatabase
from mtg_analyzer.services.game_session import GameSessionManager
from mtg_analyzer.services.lazy_card_loader import LoadCardsResult
from mtg_analyzer.services.replay import (
    blank_replay,
    build_replay_engine,
    serialize_replay,
)


def _bears():
    return Card(
        id="Bears",
        name="Grizzly Bears",
        type_line="Creature — Bear",
        is_creature=True,
        power=2,
        toughness=2,
        color_identity={"G"},
    )


def _forest():
    return Card(id="Forest", name="Forest", type_line="Basic Land — Forest", is_land=True)


class _FakeLoader:
    def __init__(self, cards):
        self._cards = cards

    def load_cards(self, names):
        found = {n: self._cards[n] for n in names if n in self._cards}
        not_found = [n for n in names if n not in self._cards]
        return LoadCardsResult(cards=found, not_found=not_found)


def _loader():
    return _FakeLoader({"Grizzly Bears": _bears(), "Forest": _forest()})


# -- Unit: descriptor build / serialize ------------------------------------


class TestReplayService:
    def test_blank_puzzle_has_one_player(self):
        desc = blank_replay(1)
        assert len(desc["players"]) == 1
        assert desc["players"][0]["name"] == "Du"

    def test_blank_with_opponent_has_two(self):
        desc = blank_replay(2)
        assert [p["id"] for p in desc["players"]] == ["p1", "p2"]

    def test_build_positions_at_main1_without_starting_turn(self):
        engine = build_replay_engine(blank_replay(1), _loader())
        # No opening hand dealt, no turn kicked off — the board is given as-is.
        assert engine.state.current_step == "main1"
        assert engine.state.players[0].hand == []

    def test_roundtrip_preserves_board_and_player_state(self):
        desc = blank_replay(2)
        desc["battlefield"].append(
            {
                "name": "Grizzly Bears",
                "card_id": "Bears",
                "owner_id": "p1",
                "controller_id": "p1",
                "tapped": True,
                "counters": {"+1/+1": 2},
                "summoning_sick": False,
            }
        )
        desc["players"][0]["zones"]["graveyard"].append(
            {"name": "Forest", "card_id": "Forest"}
        )
        desc["players"][1]["life"] = 12
        desc["players"][1]["poison"] = 4
        desc["players"][0]["counters"] = {"energy": 3}

        engine = build_replay_engine(desc, _loader())
        again = serialize_replay(engine.state)

        assert again["turn_nr"] == 1
        assert again["players"][1]["life"] == 12
        assert again["players"][1]["poison"] == 4
        assert again["players"][0]["counters"] == {"energy": 3}
        bear = again["battlefield"][0]
        assert bear["tapped"] is True
        assert bear["counters"] == {"+1/+1": 2}
        assert again["players"][0]["zones"]["graveyard"][0]["name"] == "Forest"

    def test_token_survives_without_cache(self):
        desc = blank_replay(1)
        desc["battlefield"].append(
            {
                "is_token": True,
                "owner_id": "p1",
                "controller_id": "p1",
                "token": {
                    "name": "Goblin",
                    "type_line": "Creature — Goblin",
                    "power": 1,
                    "toughness": 1,
                    "colors": ["R"],
                },
            }
        )
        # An empty loader — the token must not need a cache entry.
        engine = build_replay_engine(desc, _FakeLoader({}))
        obj = engine.state.battlefield[0]
        assert obj.is_token
        assert (obj.power, obj.toughness) == (1, 1)

    def test_poison_ten_is_a_state_based_loss(self):
        desc = blank_replay(1)
        desc["players"][0]["poison"] = 10
        engine = build_replay_engine(desc, _loader())
        engine.rules.check_state_based_actions()
        player = engine.state.players[0]
        assert player.has_lost
        assert player.loss_reason == "poison"


# -- API: start / edit / export --------------------------------------------


def _setup():
    manager = GameSessionManager()
    deck_db = DeckDatabase()
    app.dependency_overrides[get_game_session_manager] = lambda: manager
    app.dependency_overrides[get_deck_database] = lambda: deck_db
    app.dependency_overrides[get_lazy_card_loader] = lambda: _loader()
    return manager


def _teardown():
    for dep in (get_game_session_manager, get_deck_database, get_lazy_card_loader):
        app.dependency_overrides.pop(dep, None)


def _battlefield(view):
    return view["state"]["battlefield"]


class TestReplayApi:
    def teardown_method(self):
        _teardown()

    def test_start_blank_puzzle(self):
        _setup()
        client = TestClient(app)
        view = client.post("/api/game/replay", json={"numPlayers": 1}).json()
        assert view["mode"] == "replay"
        assert len(view["state"]["players"]) == 1

    def test_start_with_opponent(self):
        _setup()
        client = TestClient(app)
        view = client.post("/api/game/replay", json={"numPlayers": 2}).json()
        assert len(view["state"]["players"]) == 2

    def test_add_tap_and_counter_on_battlefield(self):
        _setup()
        client = TestClient(app)
        sid = client.post("/api/game/replay", json={"numPlayers": 2}).json()["session_id"]

        add = client.post(
            f"/api/game/{sid}/action",
            json={"type": "edit_add_object", "zone": "battlefield",
                  "owner_id": "p1", "name": "Grizzly Bears"},
        ).json()
        iid = _battlefield(add)[0]["instance_id"]
        assert _battlefield(add)[0]["power"] == 2

        client.post(
            f"/api/game/{sid}/action",
            json={"type": "edit_set_flags", "instance_id": iid, "tapped": True},
        )
        view = client.post(
            f"/api/game/{sid}/action",
            json={"type": "edit_set_counters", "instance_id": iid,
                  "counter": "+1/+1", "amount": 1},
        ).json()
        obj = _battlefield(view)[0]
        assert obj["tapped"] is True
        assert obj["power"] == 3  # 2/2 + one +1/+1 counter, folded by the layer engine

    def test_add_token(self):
        _setup()
        client = TestClient(app)
        sid = client.post("/api/game/replay", json={"numPlayers": 1}).json()["session_id"]
        view = client.post(
            f"/api/game/{sid}/action",
            json={"type": "edit_add_object", "zone": "battlefield", "owner_id": "p1",
                  "token": {"name": "Soldier", "type_line": "Creature — Soldier",
                            "power": 1, "toughness": 1, "colors": ["W"]}},
        ).json()
        obj = _battlefield(view)[0]
        assert obj["is_token"] is True
        assert obj["power"] == 1

    def test_token_rejected_off_battlefield(self):
        _setup()
        client = TestClient(app)
        sid = client.post("/api/game/replay", json={"numPlayers": 1}).json()["session_id"]
        token = {"name": "Soldier", "type_line": "Creature — Soldier",
                 "power": 1, "toughness": 1, "colors": ["W"]}
        for zone in ("hand", "graveyard", "library", "exile", "command"):
            resp = client.post(
                f"/api/game/{sid}/action",
                json={"type": "edit_add_object", "zone": zone, "owner_id": "p1", "token": token},
            )
            assert resp.status_code == 400, zone

    def test_token_cannot_be_moved_off_battlefield(self):
        _setup()
        client = TestClient(app)
        sid = client.post("/api/game/replay", json={"numPlayers": 2}).json()["session_id"]
        add = client.post(
            f"/api/game/{sid}/action",
            json={"type": "edit_add_object", "zone": "battlefield", "owner_id": "p1",
                  "token": {"name": "Soldier", "type_line": "Creature — Soldier",
                            "power": 1, "toughness": 1, "colors": ["W"]}},
        ).json()
        iid = _battlefield(add)[0]["instance_id"]
        resp = client.post(
            f"/api/game/{sid}/action",
            json={"type": "edit_move_object", "instance_id": iid, "zone": "graveyard", "owner_id": "p1"},
        )
        assert resp.status_code == 400
        # Still on the battlefield, untouched.
        view = client.post(f"/api/game/{sid}/action", json={"type": "edit_set_turn", "internal_turn": 2}).json()
        assert len(_battlefield(view)) == 1
        assert view["state"]["internal_turn"]["number"] == 2
        assert view["state"]["turn_nr"] == 1

    def test_set_life_and_poison(self):
        _setup()
        client = TestClient(app)
        sid = client.post("/api/game/replay", json={"numPlayers": 2}).json()["session_id"]
        client.post(f"/api/game/{sid}/action",
                    json={"type": "edit_set_life", "player_id": "p2", "value": 7})
        view = client.post(f"/api/game/{sid}/action",
                           json={"type": "edit_set_poison", "player_id": "p2", "value": 3}).json()
        p2 = next(p for p in view["state"]["players"] if p["id"] == "p2")
        assert p2["life"] == 7
        assert p2["poison"] == 3

    def test_set_mana_pool(self):
        _setup()
        client = TestClient(app)
        sid = client.post("/api/game/replay", json={"numPlayers": 1}).json()["session_id"]
        view = client.post(
            f"/api/game/{sid}/action",
            json={"type": "edit_set_mana", "player_id": "p1", "mana_type": "R", "value": 3},
        ).json()
        p1 = view["state"]["players"][0]
        assert p1["mana_pool"]["R"] == 3
        assert p1["mana_pool"]["W"] == 0

        # Overwrites, not adds.
        view = client.post(
            f"/api/game/{sid}/action",
            json={"type": "edit_set_mana", "player_id": "p1", "mana_type": "R", "value": 1},
        ).json()
        assert view["state"]["players"][0]["mana_pool"]["R"] == 1

        resp = client.post(
            f"/api/game/{sid}/action",
            json={"type": "edit_set_mana", "player_id": "p1", "mana_type": "not-a-color", "value": 1},
        )
        assert resp.status_code == 400

    def test_move_and_remove(self):
        _setup()
        client = TestClient(app)
        sid = client.post("/api/game/replay", json={"numPlayers": 1}).json()["session_id"]
        add = client.post(
            f"/api/game/{sid}/action",
            json={"type": "edit_add_object", "zone": "hand", "owner_id": "p1",
                  "name": "Grizzly Bears"},
        ).json()
        iid = add["state"]["players"][0]["hand"][0]["instance_id"]

        moved = client.post(
            f"/api/game/{sid}/action",
            json={"type": "edit_move_object", "instance_id": iid,
                  "zone": "graveyard", "owner_id": "p1"},
        ).json()
        p1 = moved["state"]["players"][0]
        assert p1["hand"] == []
        assert p1["graveyard"][0]["instance_id"] == iid

        removed = client.post(
            f"/api/game/{sid}/action",
            json={"type": "edit_remove_object", "instance_id": iid},
        ).json()
        assert removed["state"]["players"][0]["graveyard"] == []

    def test_reorder_library_moves_toward_top(self):
        _setup()
        client = TestClient(app)
        sid = client.post("/api/game/replay", json={"numPlayers": 1}).json()["session_id"]

        def add(name):
            view = client.post(
                f"/api/game/{sid}/action",
                json={"type": "edit_add_object", "zone": "library", "owner_id": "p1", "name": name},
            ).json()
            return view["state"]["players"][0]["library"]

        add("Grizzly Bears")
        add("Forest")
        lib = add("Grizzly Bears")
        # Stored bottom-first (the *end* is the top of the deck): [Bears1, Forest, Bears2].
        assert [o["name"] for o in lib] == ["Grizzly Bears", "Forest", "Grizzly Bears"]
        forest_iid = lib[1]["instance_id"]

        view = client.post(
            f"/api/game/{sid}/action",
            json={"type": "edit_reorder_object", "instance_id": forest_iid, "direction": "up"},
        ).json()
        lib = view["state"]["players"][0]["library"]
        # Forest swapped with its neighbor toward the end — now on top.
        assert [o["name"] for o in lib] == ["Grizzly Bears", "Grizzly Bears", "Forest"]
        assert lib[-1]["instance_id"] == forest_iid

        view = client.post(
            f"/api/game/{sid}/action",
            json={"type": "edit_reorder_object", "instance_id": forest_iid, "direction": "down"},
        ).json()
        lib = view["state"]["players"][0]["library"]
        assert [o["name"] for o in lib] == ["Grizzly Bears", "Forest", "Grizzly Bears"]

        # Already at the bottom — "down" is a no-op, not an error.
        client.post(
            f"/api/game/{sid}/action",
            json={"type": "edit_reorder_object", "instance_id": forest_iid, "direction": "down"},
        )
        view = client.post(
            f"/api/game/{sid}/action",
            json={"type": "edit_reorder_object", "instance_id": forest_iid, "direction": "down"},
        ).json()
        lib = view["state"]["players"][0]["library"]
        assert [o["name"] for o in lib] == ["Forest", "Grizzly Bears", "Grizzly Bears"]

    def test_edit_rejected_in_goldfish(self):
        manager = _setup()
        # Build a goldfish session directly (no legal-deck plumbing needed here).
        from mtg_analyzer.services.game_session import build_goldfish_engine, GameSession, GOLDFISH
        engine = build_goldfish_engine([_forest()] * 5, player_name="You")
        session = GameSession(engine, mode=GOLDFISH)
        manager._sessions[session.id] = session
        client = TestClient(app)
        resp = client.post(
            f"/api/game/{session.id}/action",
            json={"type": "edit_set_life", "player_id": "p1", "value": 1},
        )
        assert resp.status_code == 400

    def test_export_then_reimport_roundtrips(self):
        _setup()
        client = TestClient(app)
        sid = client.post("/api/game/replay", json={"numPlayers": 2}).json()["session_id"]
        add = client.post(
            f"/api/game/{sid}/action",
            json={"type": "edit_add_object", "zone": "battlefield", "owner_id": "p1",
                  "name": "Grizzly Bears", "tapped": True},
        ).json()
        assert _battlefield(add)[0]["tapped"] is True

        exported = client.get(f"/api/game/{sid}/replay-export").json()
        assert exported["format"] == "mtg-replay"
        assert exported["turn_nr"] == 1

        reloaded = client.post("/api/game/replay", json={"replay": exported}).json()
        assert _battlefield(reloaded)[0]["name"] == "Grizzly Bears"
        assert _battlefield(reloaded)[0]["tapped"] is True
