"""WebSocket /ws/game/{game_id}: real-time relay onto a server-held session.

Reference: docs/implementation-state/Done_Backend.md "HTTP API foundation",
docs/concepts/04_SERVER_CLIENT_ARCHITECTURE.md PART 4 "WebSocket Messages".

Accepts connections grouped by game_id and, for each client's
`player_action` message, runs `action` through the `GameSession` registered
under that game_id in the same process-wide `GameSessionManager` the REST
API (`api/game.py`) uses (`api/dependencies.get_game_session_manager` — a
session started via `POST /api/game/goldfish`/`/replay`/etc. is reachable
here by its `session_id`), then broadcasts the resulting session view to
every client connected to that game_id as a `game_state_update`. An unknown
game_id or an illegal action produces an `error` reply to the sender only —
nothing changed, so there is nothing to broadcast. Solo play still goes
through the REST session API directly (fine for one player); this channel
is what a future interactive multiplayer session (`create_multiplayer`,
still a stub) would use to push an opponent's moves.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from mtg_analyzer.api.dependencies import get_game_session_manager
from mtg_analyzer.services.game_session import GameActionError, GameSessionManager

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
async def game_websocket(
    websocket: WebSocket,
    game_id: str,
    sessions: GameSessionManager = Depends(get_game_session_manager),
) -> None:
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

            await _handle_player_action(websocket, game_id, message, sessions)
    except WebSocketDisconnect:
        manager.disconnect(game_id, websocket)


async def _handle_player_action(
    websocket: WebSocket,
    game_id: str,
    message: dict[str, Any],
    sessions: GameSessionManager,
) -> None:
    """Run one `player_action` through game_id's session, then broadcast.

    `action` must already be shaped like an entry from the session's
    `legal_actions` (a `type` plus whatever `instance_id`/`targets`/etc. it
    needs — the same payload `POST /api/game/{id}/action` takes). Failures
    (no such game_id, or `GameActionError` from an illegal/malformed action)
    reply to the sender alone, mirroring the "Invalid JSON"/"Unknown message
    type" replies above.
    """
    action = message.get("action")
    if not isinstance(action, dict) or "type" not in action:
        await websocket.send_json(
            {"type": "error", "message": "player_action needs an 'action' object with a 'type'"}
        )
        return

    try:
        session = sessions.get(game_id)
    except KeyError:
        await websocket.send_json({"type": "error", "message": f'no game session "{game_id}"'})
        return

    try:
        view = session.apply_action(action)
    except GameActionError as exc:
        await websocket.send_json({"type": "error", "message": str(exc)})
        return

    await manager.broadcast(
        game_id,
        {
            "type": "game_state_update",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "game_id": game_id,
            "player_id": message.get("player_id"),
            "view": view,
        },
    )
