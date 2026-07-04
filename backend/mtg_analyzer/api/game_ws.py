"""WebSocket /ws/game/{game_id}: connection plumbing for real-time game updates.

Reference: backend/ToDo_Backend.md "HTTP API foundation",
docs/04_SERVER_CLIENT_ARCHITECTURE.md PART 4 "WebSocket Messages".

No game engine exists yet (see backend/ToDo_Backend.md "Game Engine" / "Rules
Engine"), so this is transport plumbing only: accept connections
grouped by game_id, and relay each client's `player_action` message to
every client connected to that same game_id as a `game_state_update`.
There is no rules validation and no server-held GameState — the relay
is a stand-in for "the server ran the action and here is the result"
so the wire protocol and both ends of the connection can be built and
tested before the real engine exists. Once it does, `_broadcast_action`
should be replaced by feeding the action into the engine and
broadcasting its actual resulting state.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter(tags=["game-ws"])


class GameConnectionManager:
    """Tracks WebSocket connections grouped by game_id, in memory only.

    Nothing here is persisted or shared across processes — restarting
    the server drops every connection, and this only works with a
    single backend process (see docs/04 "WebSocket Scaling" for the
    eventual pub/sub-backed multi-process version).
    """

    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = {}

    async def connect(self, game_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.setdefault(game_id, set()).add(websocket)

    def disconnect(self, game_id: str, websocket: WebSocket) -> None:
        connections = self._connections.get(game_id)
        if not connections:
            return
        connections.discard(websocket)
        if not connections:
            del self._connections[game_id]

    async def broadcast(self, game_id: str, message: dict[str, object]) -> None:
        for websocket in list(self._connections.get(game_id, ())):
            await websocket.send_json(message)


manager = GameConnectionManager()


@router.websocket("/ws/game/{game_id}")
async def game_websocket(websocket: WebSocket, game_id: str) -> None:
    await manager.connect(game_id, websocket)
    try:
        while True:
            try:
                message = await websocket.receive_json()
            except (json.JSONDecodeError, UnicodeDecodeError):
                await websocket.send_json({"type": "error", "message": "Invalid JSON message"})
                continue

            if not isinstance(message, dict) or message.get("type") != "player_action":
                got = message.get("type") if isinstance(message, dict) else message
                await websocket.send_json(
                    {"type": "error", "message": f"Unknown message type: {got!r}"}
                )
                continue

            await manager.broadcast(
                game_id,
                {
                    "type": "game_state_update",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "game_id": game_id,
                    "player_id": message.get("player_id"),
                    "action": message.get("action"),
                },
            )
    except WebSocketDisconnect:
        manager.disconnect(game_id, websocket)
