"""WebSocket /ws/lobby: presence + live pushes for the multiplayer tab (UC4).

Reference: docs/concepts/04_SERVER_CLIENT_ARCHITECTURE.md PART 4,
mtg_analyzer/services/lobby.py.

One socket per client, opened as soon as the Multiplayer tab is first
visited and held for as long as the app is open. It carries three things:

* **Presence.** Having the socket at all makes you ``online``; the client
  reports ``available`` while it is actually sitting in the lobby, and the
  lobby derives ``playing`` itself from holding a seat (`Lobby.
  set_presence`). Losing the socket removes the player — that's the only
  disconnect signal this app has, since there is no auth and no session
  cookie to expire.

* **Lobby updates.** Any change (someone connects, a game forms, a seat
  readies up) is broadcast to everyone as a fresh snapshot, so the Setup
  screen never polls.

* **Board updates.** When a game's state changes, each participant is sent
  *their own* view — `GameSession.view(perspective=...)` for a seat,
  `observer_view()` for a watcher — rather than one shared payload, so the
  server-side redaction (`services/game_session.py`) is the only thing
  that ever decides who sees a hand.

Like `game_ws.py` this is in-memory and single-process: restarting the
server drops every connection and empties the lobby with it.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect

from mtg_analyzer.api.dependencies import get_game_session_manager, get_lobby
from mtg_analyzer.services.bots import bots_for_game, run_bots
from mtg_analyzer.services.game_session import GameActionError, GameSession, GameSessionManager
from mtg_analyzer.services.lobby import AVAILABLE, ONLINE, Lobby, LobbyError, LobbyGame

logger = logging.getLogger(__name__)

router = APIRouter(tags=["multiplayer-ws"])

#: How often the watchdog checks for idle/absent players. Well under the
#: shortest timeout it enforces, so a deadline is acted on promptly without
#: the loop itself being a meaningful cost when nothing is happening.
SWEEP_INTERVAL_SECONDS = 1.0

#: Safety cap on `pass_for_absent_players`' loop — it advances the game a
#: step per full round of passes, and an empty table must not spin forever.
_MAX_AUTO_PASSES = 40


class LobbyConnectionManager:
    """Every open `/ws/lobby` socket, keyed by the lobby player it belongs to."""

    def __init__(self) -> None:
        self._sockets: dict[str, WebSocket] = {}

    async def connect(self, player_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self._sockets[player_id] = websocket

    def disconnect(self, player_id: str) -> None:
        self._sockets.pop(player_id, None)

    def is_connected(self, player_id: str) -> bool:
        return player_id in self._sockets

    async def close(self, player_id: str, reason: str) -> None:
        """Drop a client's socket from this side (takeover, or idle timeout).

        Sends a final ``disconnected`` frame first so the client can say
        *why* it was dropped instead of only seeing the socket vanish — the
        difference between "you were idle" and "your network died" matters
        to the person staring at the screen.
        """
        socket = self._sockets.pop(player_id, None)
        if socket is None:
            return
        try:
            await socket.send_json({"type": "disconnected", "reason": reason})
            await socket.close()
        except (RuntimeError, WebSocketDisconnect):
            pass  # already gone; nothing to tell it

    async def send(self, player_id: str, message: dict[str, Any]) -> None:
        socket = self._sockets.get(player_id)
        if socket is None:
            return
        try:
            await socket.send_json(message)
        except (RuntimeError, WebSocketDisconnect):
            # The peer went away between the state change and this push;
            # the socket's own receive loop will clean it up.
            self.disconnect(player_id)

    async def broadcast(self, message: dict[str, Any]) -> None:
        for player_id in list(self._sockets):
            await self.send(player_id, message)

    async def broadcast_lobby(self, lobby: Lobby) -> None:
        await self.broadcast({"type": "lobby_update", "lobby": lobby.snapshot()})

    async def broadcast_game(self, game: LobbyGame, session: Optional[GameSession]) -> None:
        """Push one game's current state to everyone at (or watching) it.

        Each recipient gets their own redacted view; the observers get the
        no-hands one. Sent per socket rather than broadcast, because the
        payloads genuinely differ per player — that asymmetry *is* the
        hidden-information rule (RULE 400.2).
        """
        for seat in game.seats:
            await self.send(
                seat.player_id,
                {
                    "type": "game_update",
                    "game": game.to_dict(),
                    "view": session.view(perspective=seat.player_id) if session else None,
                },
            )
        for observer_id in game.observer_ids:
            await self.send(
                observer_id,
                {
                    "type": "game_update",
                    "game": game.to_dict(),
                    "view": session.observer_view() if session else None,
                },
            )


manager = LobbyConnectionManager()


@router.websocket("/ws/lobby")
async def lobby_websocket(
    websocket: WebSocket,
    name: str = Query(default="Spieler"),
    player_id: Optional[str] = Query(default=None),
    lobby: Lobby = Depends(get_lobby),
    sessions: GameSessionManager = Depends(get_game_session_manager),
) -> None:
    """Register a client, then hold the socket open for presence + pushes.

    Identity is the **player name** (`services/lobby.py`): reconnecting with
    the name from the Profil tab walks back into the same seat, mid-game,
    which is what makes a page reload survivable. ``player_id`` is still
    accepted — a client that kept its id saves a lookup and can rename
    itself — but it isn't needed for a reclaim any more.

    Reconnecting while an older socket for the same player is still
    registered *takes over*: the old one is closed with a ``replaced``
    reason. That's the right default because the overwhelmingly common
    cause is a dead socket the server hasn't noticed yet, and refusing
    would lock a player out of their own game.
    """
    reclaimed = manager.is_connected(player_id) if player_id else False
    player = lobby.connect(name=name, player_id=player_id)
    if manager.is_connected(player.id):
        reclaimed = True
        await manager.close(player.id, "replaced")
    await manager.connect(player.id, websocket)
    await websocket.send_json(
        {
            "type": "welcome",
            "player_id": player.id,
            "name": player.name,
            "reclaimed": reclaimed,
            "lobby": lobby.snapshot(),
        }
    )
    await manager.broadcast(
        {"type": "player_reconnected", "player_id": player.id, "name": player.name}
    )
    await manager.broadcast_lobby(lobby)
    # Someone rejoining mid-game has a stale (or empty) board; push the
    # current position straight away rather than making them wait for the
    # next move to happen.
    await _push_own_game(player.id, lobby, sessions)
    try:
        while True:
            try:
                message = await websocket.receive_json()
            except (json.JSONDecodeError, UnicodeDecodeError):
                await websocket.send_json({"type": "error", "message": "Invalid JSON message"})
                continue
            if not isinstance(message, dict):
                continue
            await _handle(message, player.id, lobby, sessions, websocket)
    except WebSocketDisconnect:
        await handle_disconnect(player.id, lobby, sessions, reason="closed")


async def handle_disconnect(
    player_id: str, lobby: Lobby, sessions: GameSessionManager, reason: str = "closed"
) -> None:
    """One side's socket went away: hold the seat, tell everyone, keep playing.

    The seat is *not* given up — `Lobby.disconnect` starts a grace period
    instead (`config.MULTIPLAYER_DISCONNECT_GRACE_SECONDS`) so a reload or a
    flaky connection isn't a forfeit. What must not happen is the table
    freezing on someone who isn't there, so if the departing player was
    holding priority the server passes it for them (RULE 117 — passing is
    always legal, and it's the only choice that can't advantage the absent
    player).
    """
    manager.disconnect(player_id)
    player = lobby.find(player_id)
    game = lobby.game_for_player(player_id) if player else None
    lobby.disconnect(player_id)
    await manager.broadcast(
        {
            "type": "player_disconnected",
            "player_id": player_id,
            "name": player.name if player else "",
            "reason": reason,
        }
    )
    if game is not None:
        session = _session_or_none(sessions, game.session_id)
        if session is not None and pass_for_absent_players(session, lobby):
            await manager.broadcast_game(game, session)
    await manager.broadcast_lobby(lobby)


def pass_for_absent_players(session: GameSession, lobby: Lobby) -> bool:
    """Pass priority on behalf of anyone who isn't connected to hold it.

    A disconnected player still has a seat (they may be back within the
    grace period), but the game can't wait on them — so the server takes
    the one action that is always legal and never gains them anything.
    Loops because passing hands priority to the *next* player, who may
    equally be gone. Returns whether anything moved.
    """
    moved = False
    for _ in range(_MAX_AUTO_PASSES):
        state = session.engine.state
        holder = state.priority_player
        if holder is None or state.game_over or state.pending_choice:
            return moved
        player = lobby.find(holder.id)
        if player is not None and player.connected:
            return moved
        try:
            session.apply_action({"type": "pass_priority"}, actor_id=holder.id)
        except GameActionError:
            return moved
        moved = True
    return moved


async def _handle(
    message: dict[str, Any],
    player_id: str,
    lobby: Lobby,
    sessions: GameSessionManager,
    websocket: WebSocket,
) -> None:
    kind = message.get("type")
    if kind == "presence":
        # "Where are you?" — the client tells us it's in the lobby
        # (``available``) or off in another tab (``online``). It can't claim
        # ``playing``; holding a seat is what decides that.
        state = message.get("state")
        try:
            lobby.set_presence(player_id, AVAILABLE if state == AVAILABLE else ONLINE)
        except LobbyError as exc:
            await websocket.send_json({"type": "error", "message": str(exc)})
            return
        await manager.broadcast_lobby(lobby)
        return
    if kind == "subscribe_game":
        # A (re)connecting client asking for the current board, e.g. after
        # a page reload mid-game.
        game = lobby.game_for_player(player_id)
        if game is None:
            return
        session = _session_or_none(sessions, game.session_id)
        await manager.broadcast_game(game, session)
        return
    if kind == "ping":
        await websocket.send_json({"type": "pong"})
        return
    await websocket.send_json({"type": "error", "message": f"Unknown message type: {kind!r}"})


def _session_or_none(sessions: GameSessionManager, session_id: Optional[str]):
    if not session_id:
        return None
    try:
        return sessions.get(session_id)
    except KeyError:
        return None


async def _push_own_game(player_id: str, lobby: Lobby, sessions: GameSessionManager) -> None:
    """Send ``player_id`` the current state of whatever game they're in."""
    game = lobby.game_for_player(player_id)
    if game is None:
        return
    await manager.broadcast_game(game, _session_or_none(sessions, game.session_id))


# -- The watchdog --------------------------------------------------------


async def sweep_once(lobby: Lobby, sessions: GameSessionManager) -> None:
    """One pass of the watchdog. Idempotent; safe to call from a test.

    Three jobs, in order, because each can create work for the next:

    1. **Idle disconnects.** A player who holds priority and hasn't acted
       within `config.MULTIPLAYER_IDLE_TIMEOUT_SECONDS` has their socket
       closed. This isn't about policing slow play — only the player the
       game is actually *waiting on* is ever checked — it's about a tab
       that went away without a clean close, which would otherwise hold the
       table hostage forever.
    2. **Expired seats.** A disconnected player whose grace period lapsed
       is dropped; in a running game that concedes for them (RULE 104.3a),
       because a seat nobody is coming back to can't be waited on.
    3. **Keeping play moving.** Priority is passed for anyone currently
       absent, and any bot at the table takes whatever turn is now its —
       so the players who *are* there can keep going, and a table of
       nothing but bots plays itself out.
    """
    for game in list(lobby.games()):
        session = _session_or_none(sessions, game.session_id)
        if session is None or session.engine.state.game_over:
            continue
        holder = session.engine.state.priority_player
        if holder is None or game.seat_for(holder.id) is None:
            continue
        if any(p.id == holder.id for p in lobby.idle_players(game)):
            await manager.close(holder.id, "idle")
            await handle_disconnect(holder.id, lobby, sessions, reason="idle")

    for player in lobby.expired_players():
        game = lobby.game_for_player(player.id)
        session = _session_or_none(sessions, game.session_id) if game else None
        if game is not None and session is not None and game.seat_for(player.id) is not None:
            try:
                session.concede(player.id)
                lobby.record_concession(game.id, player.id)
            except GameActionError:
                pass
        await manager.close(player.id, "timeout")
        lobby.forget(player.id)
        if game is not None:
            if session is not None and session.engine.state.game_over:
                try:
                    lobby.finish(game.id)
                except LobbyError:
                    pass
            await manager.broadcast_game(game, session)
        await manager.broadcast_lobby(lobby)

    for game in list(lobby.games()):
        session = _session_or_none(sessions, game.session_id)
        if session is None:
            continue
        moved = pass_for_absent_players(session, lobby)
        # Bots normally act inside the request that provoked them
        # (`api/multiplayer.py`), but two things can leave one holding
        # priority with nobody about to make an HTTP call: a table of
        # nothing but bots, and a bot whose turn came round because the
        # server just passed for an absent human.
        moved = run_bots(session, bots_for_game(game)) or moved
        if moved:
            if session.engine.state.game_over:
                try:
                    lobby.finish(game.id)
                except LobbyError:
                    pass
            await manager.broadcast_game(game, session)


async def sweeper(lobby: Lobby, sessions: GameSessionManager) -> None:
    """Run `sweep_once` forever. Started by the app's lifespan (`api/app.py`).

    Failures are swallowed deliberately: this is a background janitor, and
    one bad game must not take the watchdog down for every other table.
    """
    while True:
        await asyncio.sleep(SWEEP_INTERVAL_SECONDS)
        try:
            await sweep_once(lobby, sessions)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — a janitor that dies is worse
            logger.exception("multiplayer sweep failed")
