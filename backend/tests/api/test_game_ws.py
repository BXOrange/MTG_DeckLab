"""Tests for WebSocket /ws/game/{game_id}: feeds player_actions into the
same server-held GameSession the REST session API uses, then broadcasts the
resulting view to every connection on that game_id.

Reference: docs/implementation-state/Done_Backend.md "HTTP API foundation",
docs/concepts/04_SERVER_CLIENT_ARCHITECTURE.md PART 4 "WebSocket Messages".
"""

from fastapi.testclient import TestClient

from mtg_analyzer.api.app import app
from mtg_analyzer.api.dependencies import get_game_session_manager
from mtg_analyzer.services.game_session import GameSessionManager
from mtg_analyzer.services.replay import blank_replay

client = TestClient(app)


def _setup() -> GameSessionManager:
    manager = GameSessionManager()
    app.dependency_overrides[get_game_session_manager] = lambda: manager
    return manager


def _teardown() -> None:
    app.dependency_overrides.pop(get_game_session_manager, None)


def _replay_session_id(manager: GameSessionManager, num_players: int = 2) -> str:
    """A real, addressable session — edit_* actions work in any board state,
    so tests don't need a fully set-up goldfish game to exercise the socket."""
    session = manager.create_replay(blank_replay(num_players), loader=None)
    return session.id


class TestGameWebSocket:
    def teardown_method(self):
        _teardown()

    def test_player_action_is_applied_and_broadcast_to_other_client_in_same_game(self):
        manager = _setup()
        game_id = _replay_session_id(manager)
        # One shared portal (`with client:`) so both sockets' server handlers
        # run on the *same* event loop: without it Starlette's TestClient gives
        # each `websocket_connect` its own loop thread, and a broadcast from
        # player_one's handler into player_two's receive stream crosses loops
        # — it does not wake a receiver that is already waiting, so the
        # `receive_json` below could hang until the pytest-timeout.
        with client, client.websocket_connect(f"/ws/game/{game_id}") as player_one:
            with client.websocket_connect(f"/ws/game/{game_id}") as player_two:
                # `websocket_connect` returns as soon as the *handshake* is
                # accepted, which is one step earlier than the server adding
                # the socket to the broadcast room (`GameConnectionManager.
                # connect` registers it after `accept()`). Sending straight
                # away therefore raced: player_one's broadcast could go out
                # before player_two was in the room, and the `receive_json`
                # below would block until the 20s pytest-timeout — roughly
                # one run in five. Round-tripping one message of player_two's
                # own closes the window: its reply can only be produced by
                # the receive loop, which starts after registration.
                player_two.send_json(
                    {
                        "type": "player_action",
                        "player_id": "p2",
                        "action": {"type": "edit_set_life", "player_id": "p2", "value": 20},
                    }
                )
                assert player_two.receive_json()["type"] == "game_state_update"

                player_one.send_json(
                    {
                        "type": "player_action",
                        "player_id": "p1",
                        "action": {"type": "edit_set_life", "player_id": "p1", "value": 15},
                    }
                )

                message = player_two.receive_json()
                assert message["type"] == "game_state_update"
                assert message["game_id"] == game_id
                assert message["player_id"] == "p1"
                assert "timestamp" in message
                players = {p["id"]: p for p in message["view"]["state"]["players"]}
                assert players["p1"]["life"] == 15

    def test_sender_also_receives_the_broadcast(self):
        manager = _setup()
        game_id = _replay_session_id(manager)
        with client.websocket_connect(f"/ws/game/{game_id}") as ws:
            ws.send_json(
                {
                    "type": "player_action",
                    "player_id": "p1",
                    "action": {"type": "edit_set_life", "player_id": "p1", "value": 3},
                }
            )
            message = ws.receive_json()
            assert message["type"] == "game_state_update"
            players = {p["id"]: p for p in message["view"]["state"]["players"]}
            assert players["p1"]["life"] == 3

    def test_different_game_ids_are_isolated(self):
        manager = _setup()
        game_a = _replay_session_id(manager)
        game_b = _replay_session_id(manager)
        with client.websocket_connect(f"/ws/game/{game_a}") as in_a:
            with client.websocket_connect(f"/ws/game/{game_b}") as in_b:
                in_a.send_json(
                    {
                        "type": "player_action",
                        "player_id": "p1",
                        "action": {"type": "edit_set_life", "player_id": "p1", "value": 5},
                    }
                )

                # The broadcast to game_a's own connection must still arrive...
                assert in_a.receive_json()["type"] == "game_state_update"
                # ...but game_b never gets it. Send a message on game_b and
                # confirm the only thing it receives is its own broadcast,
                # not a leaked one from game_a.
                in_b.send_json(
                    {
                        "type": "player_action",
                        "player_id": "p2",
                        "action": {"type": "edit_set_life", "player_id": "p2", "value": 7},
                    }
                )
                message = in_b.receive_json()
                assert message["player_id"] == "p2"
                players = {p["id"]: p for p in message["view"]["state"]["players"]}
                assert players["p2"]["life"] == 7

    def test_unknown_message_type_returns_error(self):
        with client.websocket_connect("/ws/game/game-err") as ws:
            ws.send_json({"type": "not_a_real_type"})
            message = ws.receive_json()
            assert message["type"] == "error"

    def test_action_for_unknown_game_id_returns_error_to_sender_only(self):
        _setup()
        with client.websocket_connect("/ws/game/no-such-game") as ws:
            ws.send_json(
                {"type": "player_action", "player_id": "p1", "action": {"type": "pass_priority"}}
            )
            message = ws.receive_json()
            assert message["type"] == "error"
            assert "no game session" in message["message"]

    def test_illegal_action_returns_error_to_sender_only(self):
        manager = _setup()
        game_id = _replay_session_id(manager)
        with client.websocket_connect(f"/ws/game/{game_id}") as ws:
            ws.send_json(
                {"type": "player_action", "player_id": "p1", "action": {"type": "not_a_real_action"}}
            )
            message = ws.receive_json()
            assert message["type"] == "error"

    def test_disconnect_removes_connection_without_error(self):
        manager = _setup()
        game_id = _replay_session_id(manager)
        action = {
            "type": "player_action",
            "player_id": "p1",
            "action": {"type": "edit_set_life", "player_id": "p1", "value": 20},
        }
        with client.websocket_connect(f"/ws/game/{game_id}") as ws:
            ws.send_json(action)
            ws.receive_json()
        # Connection closed cleanly; a fresh one to the same game_id still works.
        with client.websocket_connect(f"/ws/game/{game_id}") as ws:
            ws.send_json(action)
            assert ws.receive_json()["type"] == "game_state_update"
