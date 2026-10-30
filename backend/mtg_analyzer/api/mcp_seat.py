"""Token-authenticated API for the one seat an MCP client plays (PLR-16).

The seat token the host copied into the client's configuration is the whole
identity: it names the table and the seat, so a client can only ever act for
its own seat, and the engine still decides whether that seat may do the thing
right now (RULE 117 priority, RULE 601.3a timing) exactly as for a human.
The client sees only `session.view(perspective=<seat>)` (RULE 400.2).
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException

from mtg_analyzer.api.dependencies import get_deck_database, get_game_session_manager, get_lobby
from mtg_analyzer.api.multiplayer import _after_move, _guard, _require_session
from mtg_analyzer.api.multiplayer_ws import manager as lobby_connections
from mtg_analyzer.api.schemas import McpSeatActionRequest, McpSeatNameRequest
from mtg_analyzer.services.deck_database import DeckDatabase
from mtg_analyzer.services.game_session import GameActionError, GameSession, GameSessionManager
from mtg_analyzer.services.lobby import Lobby, LobbyError, LobbyGame, Seat

router = APIRouter(prefix="/api/mcp-seat", tags=["mcp-seat"])

#: Longest a single `wait` call may block. Kept below common client/tool
#: timeouts so the adapter re-polls instead of the transport giving up.
MCP_WAIT_MAX_SECONDS = 25.0

#: Spacing of the checks inside `wait`; the engine has no push channel for a
#: seat, and a few checks a second is cheap next to an LLM turn.
MCP_WAIT_POLL_SECONDS = 0.5

_BEARER_PREFIX = "bearer "


def _seat_for_request(authorization: Optional[str], lobby: Lobby) -> tuple[LobbyGame, Seat]:
    """Resolve ``Authorization: Bearer <seat token>`` or raise 401."""
    value = (authorization or "").strip()
    token = value[len(_BEARER_PREFIX):].strip() if value.lower().startswith(_BEARER_PREFIX) else ""
    found = lobby.seat_for_token(token) if token else None
    if found is None:
        raise HTTPException(401, "unknown or revoked seat token")
    return found


async def _beat(lobby: Lobby, game: LobbyGame, seat: Seat) -> None:
    """Record a sign of life; the lobby only needs a push when it changed."""
    if lobby.mcp_heartbeat(game, seat):
        await lobby_connections.broadcast_lobby(lobby)


def _payload(game: LobbyGame, seat: Seat, session: Optional[GameSession]) -> dict[str, Any]:
    return {
        "game": game.to_dict(),
        "seat_id": seat.player_id,
        "view": session.view(perspective=seat.player_id) if session is not None else None,
    }


def _session_or_none(game: LobbyGame, sessions: GameSessionManager) -> Optional[GameSession]:
    if not game.session_id:
        return None
    try:
        return sessions.get(game.session_id)
    except KeyError:
        return None


@router.get("/view")
async def seat_view(
    authorization: Optional[str] = Header(default=None),
    lobby: Lobby = Depends(get_lobby),
    sessions: GameSessionManager = Depends(get_game_session_manager),
) -> dict[str, Any]:
    """This seat's redacted view; ``view`` is null until the game starts."""
    game, seat = _seat_for_request(authorization, lobby)
    await _beat(lobby, game, seat)
    return _payload(game, seat, _session_or_none(game, sessions))


@router.post("/name")
async def seat_name(
    request: McpSeatNameRequest,
    authorization: Optional[str] = Header(default=None),
    lobby: Lobby = Depends(get_lobby),
) -> dict[str, Any]:
    """Let the client name its seat; only while the table is still forming."""
    game, seat = _seat_for_request(authorization, lobby)
    await _beat(lobby, game, seat)
    try:
        name = lobby.rename_mcp_seat(game, seat, request.name)
    except LobbyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await lobby_connections.broadcast_lobby(lobby)
    return {"name": name, "seat_id": seat.player_id}


@router.get("/deck")
async def seat_deck(
    authorization: Optional[str] = Header(default=None),
    lobby: Lobby = Depends(get_lobby),
    decks: DeckDatabase = Depends(get_deck_database),
) -> dict[str, Any]:
    """The seat's own decklist as saved, i.e. before any shuffle.

    A player knows their own list, so this reveals nothing about anyone else
    and nothing about library order (RULE 400.2 only protects hidden zones
    from *other* players).
    """
    game, seat = _seat_for_request(authorization, lobby)
    await _beat(lobby, game, seat)
    deck = decks.get_deck(seat.deck_id) if seat.deck_id else None
    if deck is None:
        raise HTTPException(404, "this seat has no deck yet")
    return {
        "seat_id": seat.player_id,
        "name": deck.name,
        "commander": deck.commander_text,
        "mainboard": deck.mainboard_text,
        "sideboard": deck.sideboard_text,
    }


@router.get("/wait")
async def seat_wait(
    timeout: float = MCP_WAIT_MAX_SECONDS,
    authorization: Optional[str] = Header(default=None),
    lobby: Lobby = Depends(get_lobby),
    sessions: GameSessionManager = Depends(get_game_session_manager),
) -> dict[str, Any]:
    """Block until the seat has something to do, the game ends, or time is up.

    "Something to do" is the same test the bot driver uses: a non-empty
    `legal_actions` for this perspective (`services/bots._one_bot_action`).
    """
    game, seat = _seat_for_request(authorization, lobby)
    deadline = time.monotonic() + max(0.0, min(timeout, MCP_WAIT_MAX_SECONDS))
    while True:
        await _beat(lobby, game, seat)
        session = _session_or_none(game, sessions)
        if session is not None and (
            session.engine.state.game_over or session.legal_actions(perspective=seat.player_id)
        ):
            return {**_payload(game, seat, session), "timed_out": False}
        if time.monotonic() >= deadline:
            return {**_payload(game, seat, session), "timed_out": True}
        await asyncio.sleep(MCP_WAIT_POLL_SECONDS)


@router.post("/action")
async def seat_action(
    request: McpSeatActionRequest,
    authorization: Optional[str] = Header(default=None),
    lobby: Lobby = Depends(get_lobby),
    sessions: GameSessionManager = Depends(get_game_session_manager),
) -> dict[str, Any]:
    """Apply one entry of this seat's `legal_actions`; rejections are a 400."""
    game, seat = _seat_for_request(authorization, lobby)
    await _beat(lobby, game, seat)
    session = _require_session(game, sessions)
    try:
        session.apply_action(request.action, actor_id=seat.player_id)
    except GameActionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {**await _after_move(lobby, game, session, seat.player_id), "seat_id": seat.player_id}


@router.post("/concede")
async def seat_concede(
    authorization: Optional[str] = Header(default=None),
    lobby: Lobby = Depends(get_lobby),
    sessions: GameSessionManager = Depends(get_game_session_manager),
) -> dict[str, Any]:
    """RULE 104.3a: leave the game."""
    game, seat = _seat_for_request(authorization, lobby)
    session = _require_session(game, sessions)
    try:
        session.concede(seat.player_id)
    except GameActionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _guard(lambda: lobby.record_concession(game.id, seat.player_id))
    return {**await _after_move(lobby, game, session, seat.player_id), "seat_id": seat.player_id}
