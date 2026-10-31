"""Read-only launcher diagnostics, enabled only with its per-launch secret."""
import os
import secrets
import threading

from fastapi import APIRouter, Header, HTTPException

from mtg_analyzer.api.dependencies import get_lobby
from mtg_analyzer.api.multiplayer_ws import manager as lobby_connections
from mtg_analyzer.api.game_ws import manager as game_connections

router = APIRouter()


@router.get("/api/console-status", include_in_schema=False)
async def console_status(x_console_token: str = Header(default="")) -> dict:
    token = os.environ.get("MTG_CONSOLE_TOKEN", "")
    if not token or not secrets.compare_digest(token, x_console_token):
        raise HTTPException(status_code=404)
    # Async route: inspect presence on the same event loop as WebSocket updates.
    lobby = get_lobby()
    return {
        "players": [p.name for p in lobby.players() if lobby_connections.is_connected(p.id)],
        "games": [{"id": g.id, "name": g.name, "status": g.status} for g in lobby.games()],
        "game_connections": sum(len(sockets) for sockets in game_connections._connections.values()),
        "threads": [t.name for t in threading.enumerate()],
    }
