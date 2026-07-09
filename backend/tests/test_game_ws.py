"""Tests for WebSocket /ws/game/{game_id}: connection plumbing only.

Reference: backend/Done_Backend.md "HTTP API foundation",
docs/04_SERVER_CLIENT_ARCHITECTURE.md PART 4 "WebSocket Messages".
"""

from fastapi.testclient import TestClient

from mtg_analyzer.api.app import app

client = TestClient(app)


class TestGameWebSocket:
    def test_player_action_is_broadcast_to_other_client_in_same_game(self):
        with client.websocket_connect("/ws/game/game-1") as player_one:
            with client.websocket_connect("/ws/game/game-1") as player_two:
                player_one.send_json(
                    {
                        "type": "player_action",
                        "game_id": "game-1",
                        "player_id": "player_1",
                        "action": {"type": "cast_spell", "card_id": "lightning_bolt"},
                    }
                )

                message = player_two.receive_json()
                assert message["type"] == "game_state_update"
                assert message["game_id"] == "game-1"
                assert message["player_id"] == "player_1"
                assert message["action"] == {"type": "cast_spell", "card_id": "lightning_bolt"}
                assert "timestamp" in message

    def test_sender_also_receives_the_broadcast(self):
        with client.websocket_connect("/ws/game/game-solo") as ws:
            ws.send_json({"type": "player_action", "player_id": "p1", "action": {"type": "pass"}})
            message = ws.receive_json()
            assert message["type"] == "game_state_update"
            assert message["action"] == {"type": "pass"}

    def test_different_game_ids_are_isolated(self):
        with client.websocket_connect("/ws/game/game-a") as in_a:
            with client.websocket_connect("/ws/game/game-b") as in_b:
                in_a.send_json({"type": "player_action", "player_id": "p1", "action": {"type": "pass"}})

                # The broadcast to game-a's own connection must still arrive...
                assert in_a.receive_json()["type"] == "game_state_update"
                # ...but game-b never gets it. Send a message on game-b and
                # confirm the only thing it receives is its own broadcast,
                # not a leaked one from game-a.
                in_b.send_json({"type": "player_action", "player_id": "p2", "action": {"type": "draw"}})
                message = in_b.receive_json()
                assert message["player_id"] == "p2"

    def test_unknown_message_type_returns_error(self):
        with client.websocket_connect("/ws/game/game-err") as ws:
            ws.send_json({"type": "not_a_real_type"})
            message = ws.receive_json()
            assert message["type"] == "error"

    def test_disconnect_removes_connection_without_error(self):
        with client.websocket_connect("/ws/game/game-disc") as ws:
            ws.send_json({"type": "player_action", "player_id": "p1", "action": {"type": "pass"}})
            ws.receive_json()
        # Connection closed cleanly; a fresh one to the same game_id still works.
        with client.websocket_connect("/ws/game/game-disc") as ws:
            ws.send_json({"type": "player_action", "player_id": "p1", "action": {"type": "pass"}})
            assert ws.receive_json()["type"] == "game_state_update"
