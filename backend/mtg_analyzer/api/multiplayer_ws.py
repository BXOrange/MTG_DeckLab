"""WebSocket /ws/lobby: presence + live pushes for the multiplayer tab (UC4).

Reference: docs/concepts/04_SERVER_CLIENT_ARCHITECTURE.md PART 4,
mtg_analyzer/services/lobby.py.

One socket per client, opened as soon as the Multiplayer tab is first
visited and held for as long as the app is open. It carries three things:

* **Presence.** Having the socket at all makes you ``online``; the client
  reports ``available`` while it is actually sitting in the lobby, and the
  lobby derives ``playing`` itself from holding a seat (`Lobby.
  set_presence`). Losing the socket removes the player (a seated one keeps
  the seat for the disconnect grace). The socket is authenticated at upgrade
  from the session cookie (PLR-9c) and the account may hold only one of them.

* **Lobby updates.** Any change (someone connects, a game forms, a seat
  readies up) is broadcast to everyone as a fresh snapshot, so the Setup
  screen never polls.

* **Board updates.** When a game's state changes, each participant is sent
  *their own* view — `GameSession.view(perspective=...)` for a seat,
  `observer_view()` for a watcher — rather than one shared payload, so the
  server-side redaction (`services/game_session.py`) is the only thing
  that ever decides who sees a hand.

This is in-memory and single-process: restarting the
server drops every connection and empties the lobby with it.
"""

from __future__ import annotations

import asyncio
import collections
import json
import logging
import secrets
import time
import weakref
from dataclasses import dataclass, field
from typing import Any, Optional

import anyio
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from mtg_analyzer.api.auth import AuthContext, websocket_context
from mtg_analyzer.api.dependencies import get_account_store, get_game_session_manager, get_lobby
from mtg_analyzer.services import account_store as acc
from mtg_analyzer.services.account_store import AccountStore
from mtg_analyzer.services.bots import bots_for_game, run_bots
from mtg_analyzer.services.game_session import GameActionError, GameSession, GameSessionManager
from mtg_analyzer.i18n import has_message, lang_from_connection, message as catalogue_message
from mtg_analyzer.services.lobby import AVAILABLE, ONLINE, Lobby, LobbyError, LobbyGame, LobbyPlayer

logger = logging.getLogger(__name__)

router = APIRouter(tags=["multiplayer-ws"])

#: How often the watchdog checks for idle/absent players. Well under the
#: shortest timeout it enforces, so a deadline is acted on promptly without
#: the loop itself being a meaningful cost when nothing is happening.
SWEEP_INTERVAL_SECONDS = 1.0

#: RFC 6455 close code 1008: the lobby refused this client (BUG-43 cap,
#: failed authentication, parallel session, rate limit).
WS_POLICY_VIOLATION = 1008

#: RFC 6455 close code 1000: an orderly close (idle, replaced, timed out).
WS_NORMAL_CLOSURE = 1000

#: Safety cap on `pass_for_absent_players`' loop — it advances the game a
#: step per full round of passes, and an empty table must not spin forever.
_MAX_AUTO_PASSES = 40

#: How long an accepted socket has to send its ``auth`` frame (BUG-39, PLR-9c).
#: The frame carries the tab id (and optionally the session CSRF proof), never
#: a secret; the wait is bounded so a silent client cannot hold a half-open
#: socket forever.
AUTH_FRAME_TIMEOUT_SECONDS = 5.0

#: The first-frame message type of the handshake.
AUTH_MESSAGE_TYPE = "auth"

#: Most sockets that may sit between "accepted" and "auth frame read" at once
#: (global, so an unauthenticated flood cannot exhaust the process); further
#: upgrades are refused before they are accepted.
MAX_PENDING_SOCKETS = 16

#: Largest text frame a client may send, in characters. Every legitimate
#: message (presence, ping, subscribe, alive) is a few dozen bytes.
WS_MAX_MESSAGE_CHARS = 4096

#: Message-rate cap per socket: at most this many frames per window. The
#: client pings every 30 s and sends a handful of control frames, so this is
#: generous for a person and fatal for a flood.
WS_RATE_LIMIT_MESSAGES = 60
WS_RATE_WINDOW_SECONDS = 10.0

#: The client's keep-alive cadence is 30 s (`lobbySocket.js` PING_INTERVAL_MS);
#: a socket silent for three of those is dead (crashed tab, vanished network)
#: and no longer locks its account out. This is the plan's "grace window".
SOCKET_STALE_SECONDS = 90.0

#: How long a same-tab reconnect waits for the old socket to answer a
#: liveness probe before deciding it is dead and replacing it.
LIVENESS_PROBE_TIMEOUT_SECONDS = 2.0

#: How often a waiting probe re-checks for the old socket's answer.
LIVENESS_POLL_SECONDS = 0.05

#: Entropy of a server-issued tab id (128 bits: never guessable, so a stolen
#: session cookie cannot evict the owner by presenting a made-up id).
TAB_ID_BYTES = 16
#: Longest tab id the server will read from a client frame (the issued ones are shorter).
TAB_ID_MAX_LENGTH = 64

#: Close reasons sent in the final ``disconnected`` frame (the frontend maps them to text).
REASON_PARALLEL_SESSION = "parallel_session"
REASON_UNAUTHENTICATED = "unauthenticated"
REASON_SESSION_ENDED = "session_ended"
REASON_AUTH_REQUIRED = "auth_required"
REASON_RATE_LIMITED = "rate_limited"
REASON_STALE = "stale"
#: Catalogue code of the localized text that goes with a disconnect reason (VIS-24); the lobby-full
#: refusal reuses the lobby's own code.
_REASON_MESSAGE_PREFIX = "ws_"
REASON_LOBBY_FULL = "lobby_full"

#: Liveness frames (server asks, client answers) for the single-session lock.
LIVENESS_MESSAGE_TYPE = "liveness"
ALIVE_MESSAGE_TYPE = "alive"


#: What sending to a peer that already went away can raise (starlette, anyio, the OS).
_SOCKET_GONE = (RuntimeError, WebSocketDisconnect, anyio.ClosedResourceError, anyio.BrokenResourceError, OSError)


class ParallelSession(Exception):
    """The account already holds a live lobby socket in another tab."""


@dataclass
class _Connection:
    """One registered socket and what the single-session lock needs to know about it."""

    websocket: WebSocket
    player_uuid: str
    session_token: str
    session_digest: str
    tab_id: str
    last_seen: float = field(default_factory=time.monotonic)
    #: `time.monotonic()` of the client's last ``alive`` answer to a liveness probe.
    alive_at: float = 0.0


class LobbyConnectionManager:
    """Every open `/ws/lobby` socket, keyed by the lobby player it belongs to.

    Also the **single-session lock** (plan section 5): one account holds one socket.
    """

    def __init__(self) -> None:
        self._sockets: dict[str, _Connection] = {}
        #: account player_uuid -> lobby player id of its live socket
        self._by_account: dict[str, str] = {}
        #: account player_uuid -> (tab_id, session digest) last issued by the server.
        #: Only a tab id found here, for this session, counts as "server-bound".
        self._tab_bindings: dict[str, tuple[str, str]] = {}
        self._pending = 0
        self._admit_locks: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock]" = (
            weakref.WeakKeyDictionary()
        )

    # -- unauthenticated-socket cap ----------------------------------------

    def reserve_pending(self) -> bool:
        """Count a socket that is not yet through the handshake; False at the cap."""
        if self._pending >= MAX_PENDING_SOCKETS:
            return False
        self._pending += 1
        return True

    def release_pending(self) -> None:
        self._pending = max(0, self._pending - 1)

    # -- registration / single-session lock --------------------------------

    async def admit(
        self, websocket: WebSocket, ctx: AuthContext, requested_tab_id: Optional[str], lobby: Lobby
    ) -> tuple[LobbyPlayer, str, bool]:
        """Decide whether ``ctx``'s account may open this socket; register it if so.

        Returns ``(player, tab_id, reclaimed)``; raises `ParallelSession` for a second
        tab, `LobbyError` when the lobby is full. Serialized so two simultaneous
        connects cannot both pass the check.

        * no live socket for the account: accepted;
        * live socket, same **server-bound** tab id (and same session): it is this
          tab reconnecting, so the old socket is probed; dead = replaced, answering =
          the tab id was copied (duplicated tab) = blocked;
        * live socket otherwise (other tab, no tab id, a guessed id, another
          session): blocked, unless it has been silent past `SOCKET_STALE_SECONDS`.

        A client-chosen tab id never evicts anyone: only the exact id issued to this
        account's session is honoured, and even then only over a dead socket.
        """
        digest = acc._digest(ctx.token)
        uuid = ctx.account.player_uuid
        async with self._admit_lock():
            old_id = self._by_account.get(uuid)
            old = self._sockets.get(old_id) if old_id else None
            if old is not None and not await self._is_replaceable(old, uuid, digest, requested_tab_id):
                raise ParallelSession()
            reclaimed = lobby.player_for_account(uuid) is not None
            player = lobby.connect(uuid, ctx.account.name)
            if old is not None:
                await self.close(old_id, "replaced")
            bound = self._tab_bindings.get(uuid)
            if requested_tab_id and bound == (requested_tab_id, digest):
                tab_id = requested_tab_id
            else:
                tab_id = secrets.token_urlsafe(TAB_ID_BYTES)
            self._tab_bindings[uuid] = (tab_id, digest)
            self._sockets[player.id] = _Connection(websocket, uuid, ctx.token, digest, tab_id)
            self._by_account[uuid] = player.id
            return player, tab_id, reclaimed

    def _admit_lock(self) -> asyncio.Lock:
        """The admission lock of the running event loop (production has one; tests start several)."""
        loop = asyncio.get_running_loop()
        lock = self._admit_locks.get(loop)
        if lock is None:
            lock = self._admit_locks[loop] = asyncio.Lock()
        return lock

    async def _is_replaceable(
        self, old: _Connection, uuid: str, digest: str, requested_tab_id: Optional[str]
    ) -> bool:
        if time.monotonic() - old.last_seen > SOCKET_STALE_SECONDS:
            return True  # missed its keep-alive window: a crashed tab must not lock the account out
        same_tab = (
            bool(requested_tab_id)
            and self._tab_bindings.get(uuid) == (requested_tab_id, digest)
            and old.tab_id == requested_tab_id
            and old.session_digest == digest
        )
        if not same_tab:
            return False
        return not await self._probe(old)

    async def _probe(self, conn: _Connection) -> bool:
        """Ask a socket whether anyone is there; False if it is gone or silent.

        Polls a timestamp the socket's own handler sets (`note_alive`) instead of waiting on
        an event, so it works across the handlers of different sockets without sharing
        loop-bound primitives.
        """
        asked = time.monotonic()
        try:
            await conn.websocket.send_json({"type": LIVENESS_MESSAGE_TYPE})
        except _SOCKET_GONE:
            return False
        deadline = asked + LIVENESS_PROBE_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if conn.alive_at >= asked:
                return True
            await asyncio.sleep(LIVENESS_POLL_SECONDS)
        return False

    def note_alive(self, player_id: str) -> None:
        conn = self._sockets.get(player_id)
        if conn is not None:
            conn.alive_at = time.monotonic()

    def touch(self, player_id: str) -> None:
        conn = self._sockets.get(player_id)
        if conn is not None:
            conn.last_seen = time.monotonic()

    def connection(self, player_id: str) -> Optional[_Connection]:
        return self._sockets.get(player_id)

    def connections(self) -> list[tuple[str, _Connection]]:
        return list(self._sockets.items())

    def is_registered(self, player_id: str, websocket: WebSocket) -> bool:
        """Whether ``websocket`` is still the socket registered for ``player_id``.

        False once it was replaced or closed from this side, so a stale handler does not
        tear down the player's *new* connection on its way out.
        """
        conn = self._sockets.get(player_id)
        return conn is not None and conn.websocket is websocket

    def disconnect(self, player_id: str) -> None:
        conn = self._sockets.pop(player_id, None)
        if conn is not None and self._by_account.get(conn.player_uuid) == player_id:
            self._by_account.pop(conn.player_uuid, None)

    def forget_tab(self, player_uuid: str) -> None:
        """Invalidate the account's issued tab id (its session ended)."""
        self._tab_bindings.pop(player_uuid, None)

    def is_connected(self, player_id: str) -> bool:
        return player_id in self._sockets

    async def close(self, player_id: str, reason: str, code: int = WS_NORMAL_CLOSURE) -> None:
        """Drop a client's socket from this side (takeover, idle timeout, session end).

        Sends a final ``disconnected`` frame first so the client can say
        *why* it was dropped instead of only seeing the socket vanish — the
        difference between "you were idle" and "your network died" matters
        to the person staring at the screen.
        """
        conn = self._sockets.get(player_id)
        if conn is None:
            return
        self.disconnect(player_id)
        try:
            frame: dict[str, Any] = {"type": "disconnected", "reason": reason}
            text = _reason_message(reason, conn.websocket)
            if text:
                frame["message"] = text
            await conn.websocket.send_json(frame)
            await conn.websocket.close(code=code)
        except _SOCKET_GONE:
            pass  # already gone; nothing to tell it

    async def send(self, player_id: str, message: dict[str, Any]) -> None:
        conn = self._sockets.get(player_id)
        if conn is None:
            return
        try:
            await conn.websocket.send_json(message)
        except _SOCKET_GONE:
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


def _reason_message(reason: str, websocket: WebSocket, **params: Any) -> str:
    """The reason's text in the socket's language (cookie, `Accept-Language`, German); "" when the
    catalogue has none."""
    code = reason if reason == REASON_LOBBY_FULL else f"{_REASON_MESSAGE_PREFIX}{reason}"
    return catalogue_message(code, lang_from_connection(websocket), **params) if has_message(code) else ""


def _error_frame(code: str, websocket: WebSocket, **params: Any) -> dict[str, Any]:
    """A non-fatal ``error`` frame: stable ``code`` plus the localized ``message``."""
    return {"type": "error", "code": code, "message": catalogue_message(code, lang_from_connection(websocket), **params)}


async def _refuse(websocket: WebSocket, reason: str) -> None:
    """Tell a socket why it is being turned away, then close it (code 1008)."""
    payload: dict[str, Any] = {"type": "disconnected", "reason": reason}
    text = _reason_message(reason, websocket)
    if text:
        payload["message"] = text
    try:
        await websocket.send_json(payload)
        await websocket.close(code=WS_POLICY_VIOLATION)
    except _SOCKET_GONE:
        pass


@dataclass(frozen=True)
class AuthFrame:
    tab_id: Optional[str]


class AuthFrameError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


async def _read_auth_frame(websocket: WebSocket, ctx: AuthContext) -> AuthFrame:
    """Read and validate the handshake frame (``{"type": "auth", "tab_id"?, "csrf_token"?}``).

    The session cookie already authenticated the upgrade; this frame carries the
    client's tab id and, when sent, the session-bound CSRF proof (verified, not
    required: strict Origin validation is the CSWSH defence, plan section 5).
    Anything else, a timeout or a malformed frame refuses the socket.
    """
    try:
        raw = await asyncio.wait_for(websocket.receive_text(), AUTH_FRAME_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        raise AuthFrameError(REASON_AUTH_REQUIRED) from None
    except WebSocketDisconnect:
        raise AuthFrameError(REASON_AUTH_REQUIRED) from None
    if len(raw) > WS_MAX_MESSAGE_CHARS:
        raise AuthFrameError(REASON_AUTH_REQUIRED)
    try:
        message = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise AuthFrameError(REASON_AUTH_REQUIRED) from None
    if not isinstance(message, dict) or message.get("type") != AUTH_MESSAGE_TYPE:
        raise AuthFrameError(REASON_AUTH_REQUIRED)
    tab_id = message.get("tab_id")
    if tab_id is not None and (not isinstance(tab_id, str) or len(tab_id) > TAB_ID_MAX_LENGTH):
        raise AuthFrameError(REASON_AUTH_REQUIRED)
    proof = message.get("csrf_token")
    if proof is not None:
        import hmac

        if not isinstance(proof, str) or not hmac.compare_digest(
            proof.encode(), ctx.session.csrf_token.encode()
        ):
            raise AuthFrameError(REASON_UNAUTHENTICATED)
    return AuthFrame(tab_id=tab_id or None)


@router.websocket("/ws/lobby")
async def lobby_websocket(
    websocket: WebSocket,
    ctx: Optional[AuthContext] = Depends(websocket_context),
    lobby: Lobby = Depends(get_lobby),
    sessions: GameSessionManager = Depends(get_game_session_manager),
    accounts: AccountStore = Depends(get_account_store),
) -> None:
    """Authenticate, register the account's lobby player, then hold the socket for pushes.

    Identity is the **session account** (PLR-9c): the cookie is checked at upgrade
    (`websocket_context`; the exact Origin by `request_guard`) before any lobby or
    game data is sent. The lobby player is the account's (`Lobby.connect`), so a
    reconnect within the disconnect grace resumes the seat and nothing a client
    sends -- a name, an id, a token -- can claim someone else's.

    One account, one socket (`LobbyConnectionManager.admit`): a second tab is
    refused with ``parallel_session`` instead of taking over, a reconnect of the
    same tab replaces its dead socket.
    """
    if not manager.reserve_pending():
        await websocket.close(code=WS_POLICY_VIOLATION)  # refused before accept
        return
    try:
        await websocket.accept()
        if ctx is None:
            await _refuse(websocket, REASON_UNAUTHENTICATED)
            return
        try:
            frame = await _read_auth_frame(websocket, ctx)
        except AuthFrameError as exc:
            await _refuse(websocket, exc.reason)
            return
        try:
            player, tab_id, reclaimed = await manager.admit(websocket, ctx, frame.tab_id, lobby)
        except ParallelSession:
            await _refuse(websocket, REASON_PARALLEL_SESSION)
            return
        except LobbyError:  # BUG-43: lobby full
            await _refuse(websocket, REASON_LOBBY_FULL)
            return
    finally:
        manager.release_pending()
    await websocket.send_json(
        {
            "type": "welcome",
            "player_id": player.id,
            "tab_id": tab_id,
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
    recent: collections.deque[float] = collections.deque()
    try:
        while True:
            raw = await websocket.receive_text()
            manager.touch(player.id)
            if not _within_rate(recent):
                await manager.close(player.id, REASON_RATE_LIMITED, WS_POLICY_VIOLATION)
                await handle_disconnect(player.id, lobby, sessions, reason=REASON_RATE_LIMITED)
                return
            # Per action: the session must still be valid (logout/expiry/disablement
            # end the socket at the next frame at the latest, the sweeper sooner).
            if not accounts.session_valid(ctx.token):
                await manager.close(player.id, REASON_SESSION_ENDED, WS_POLICY_VIOLATION)
                await handle_disconnect(player.id, lobby, sessions, reason=REASON_SESSION_ENDED)
                return
            message = _parse_message(raw)
            if message is None:
                await websocket.send_json(_error_frame("ws_invalid_message", websocket))
                continue
            await _handle(message, player.id, lobby, sessions, websocket)
    except WebSocketDisconnect:
        # A socket that was replaced or closed from this side already did its bookkeeping.
        if manager.is_registered(player.id, websocket):
            await handle_disconnect(player.id, lobby, sessions, reason="closed")


def _within_rate(recent: "collections.deque[float]") -> bool:
    """Sliding-window message-rate check; records this message."""
    now = time.monotonic()
    while recent and now - recent[0] > WS_RATE_WINDOW_SECONDS:
        recent.popleft()
    recent.append(now)
    return len(recent) <= WS_RATE_LIMIT_MESSAGES


def _parse_message(raw: str) -> Optional[dict[str, Any]]:
    """A well-formed, size-limited JSON object, or None."""
    if len(raw) > WS_MAX_MESSAGE_CHARS:
        return None
    try:
        message = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return message if isinstance(message, dict) and isinstance(message.get("type"), str) else None


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
            await websocket.send_json(
                {"type": "error", "code": exc.code, "message": exc.render(lang_from_connection(websocket))}
            )
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
    if kind == ALIVE_MESSAGE_TYPE:
        manager.note_alive(player_id)  # answer to a single-session liveness probe
        return
    if kind == "ping":
        # PLR-5: counts as liveness, same as a real game action
        # (`api/multiplayer.py`'s `apply_action`) — otherwise the idle
        # watchdog (`sweep_once`) only ever sees silence from a player who
        # is genuinely still there but just thinking, and disconnects/
        # instantly-reconnects them for it.
        lobby.touch(player_id)
        await websocket.send_json({"type": "pong"})
        return
    await websocket.send_json(_error_frame("ws_unknown_message_type", websocket, kind=repr(kind)))


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


async def sweep_once(
    lobby: Lobby, sessions: GameSessionManager, accounts: Optional[AccountStore] = None
) -> None:
    """One pass of the watchdog. Idempotent; safe to call from a test.

    Jobs (0 is the BUG-43 session TTL sweep), in order, because each can create work for the next:

    0. **Account sessions and dead sockets (PLR-9c).** A socket whose account
       session was logged out, expired, disabled or deleted is closed, and one
       silent past `SOCKET_STALE_SECONDS` counts as dead; both then follow the
       ordinary disconnect-grace rules (the seat is held, a re-login within the
       grace resumes it). ``accounts`` is optional so a test of the other jobs
       needs no store; production always passes it (`api/app.py`'s lifespan).
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

    The PLR-4 client-token expiry (and its `player_assets` purge by display name)
    is gone with client tokens; asset cleanup follows account deletion (PLR-16,
    `services/player_assets.bind_account_cleanup`).
    """
    # BUG-43: idle goldfish/solo/replay sessions (and orphaned table sessions)
    # expire; tables' own sessions are protected inside the manager. Cheap:
    # one pass over a dict. Runs first so a dead session isn't looked up below.
    sessions.sweep()

    now = time.monotonic()
    for player_id, conn in manager.connections():
        if accounts is not None and not accounts.session_valid(conn.session_token):
            manager.forget_tab(conn.player_uuid)
            reason = REASON_SESSION_ENDED
        elif now - conn.last_seen > SOCKET_STALE_SECONDS:
            reason = REASON_STALE
        else:
            continue
        await manager.close(player_id, reason, WS_POLICY_VIOLATION)
        await handle_disconnect(player_id, lobby, sessions, reason=reason)

    if accounts is not None:
        # PLR-9d: a deleted account's seat is freed at once (no disconnect grace); the
        # expired-seat pass below concedes for it and removes it.
        for deleted_uuid in accounts.drain_deleted():
            gone = lobby.player_for_account(deleted_uuid)
            if gone is not None:
                await manager.close(gone.id, REASON_SESSION_ENDED, WS_POLICY_VIOLATION)
                lobby.expire_now(gone.id)

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


async def sweeper(
    lobby: Lobby, sessions: GameSessionManager, accounts: Optional[AccountStore] = None
) -> None:
    """Run `sweep_once` forever. Started by the app's lifespan (`api/app.py`).

    Failures are swallowed deliberately: this is a background janitor, and
    one bad game must not take the watchdog down for every other table.
    """
    while True:
        await asyncio.sleep(SWEEP_INTERVAL_SECONDS)
        try:
            await sweep_once(lobby, sessions, accounts)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — a janitor that dies is worse
            logger.exception("multiplayer sweep failed")
