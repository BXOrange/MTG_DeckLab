"""Multiplayer endpoints: the lobby, game setup, and playing a shared game (UC4).

Reference: docs/requirements/02_MVP_USECASES_REVISED.md UC4,
mtg_analyzer/services/lobby.py, mtg_analyzer/services/game_session.py.

Two layers sit behind these routes and they stay strictly separated:

* the **lobby** (`services/lobby.py`) — people and tables, no Magic; and
* the **session** (`services/game_session.py`) — one `GameEngine`, seat
  by seat, with every view redacted for the seat that asked for it.

This module is the only place that bridges them: it resolves each seat's
saved deck into real `Card`s (exactly like `api/game.py` does for
goldfish, sharing its `expand_entries`), builds the `GameSession`, and
hands the id back to the lobby.

* ``POST /api/multiplayer/connect``               — register (HTTP fallback
                                                    for `/ws/lobby`).
* ``GET  /api/multiplayer/lobby``                 — players + games snapshot.
* ``POST /api/multiplayer/games``                 — open a table.
* ``POST /api/multiplayer/games/{id}/join``       — take a seat.
* ``POST /api/multiplayer/games/{id}/observe``    — watch instead.
* ``POST /api/multiplayer/games/{id}/leave``      — give up a seat/watch.
* ``POST /api/multiplayer/games/{id}/deck``       — pick this seat's deck.
* ``POST /api/multiplayer/games/{id}/banner``     — this seat's banner colour.
* ``GET  /api/multiplayer/bots``                  — the pickable bot kinds.
* ``POST /api/multiplayer/games/{id}/bots``       — host: seat a bot.
* ``POST /api/multiplayer/games/{id}/bots/remove``— host: unseat one.
* ``POST /api/multiplayer/games/{id}/options``    — host: table settings.
* ``POST /api/multiplayer/games/{id}/ready``      — accept as configured.
* ``POST /api/multiplayer/games/{id}/start``      — all accepted → play.
* ``GET  /api/multiplayer/games/{id}``            — this seat's view.
* ``POST /api/multiplayer/games/{id}/action``     — one action, as this seat.
* ``POST /api/multiplayer/games/{id}/concede``    — RULE 104.3a.

Every state-changing route pushes the result over `/ws/lobby`
(`api/multiplayer_ws.py`) so the other clients update without polling; the
REST response is that same payload for the caller, so a client that has
no socket yet still works.

A seat can be held by a **bot** (`services/bots.py`). Bots are driven from
here rather than from a loop of their own: `_run_bots` is called after
anything that changes the game and *before* the broadcast, so what gets
pushed is the position after the bots have finished answering — one
update, not a flicker of intermediate boards. (The other driver is the
watchdog tick in `api/multiplayer_ws.py`, which is what moves a table with
no human at it.)
"""

from __future__ import annotations

import random
import sys
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends

from mtg_analyzer.i18n import api_error, error_from
from mtg_analyzer.api.dependencies import (
    get_deck_database,
    get_game_session_manager,
    get_lazy_card_loader,
    get_lobby,
)
from mtg_analyzer.api.auth import AuthContext, current_account
from mtg_analyzer.api.game import resolve_deck
from mtg_analyzer.models.decks.deck import Deck
from mtg_analyzer.api.multiplayer_ws import manager as lobby_connections
from mtg_analyzer.api.schemas import (
    MultiplayerActionRequest,
    MultiplayerBannerColorRequest,
    MultiplayerBotRemoveRequest,
    MultiplayerBotRequest,
    MultiplayerDeckRequest,
    MultiplayerGameRequest,
    MultiplayerOptionsRequest,
    MultiplayerPlayerRequest,
    MultiplayerReadyRequest,
    MultiplayerUiDraftRequest,
)
from mtg_analyzer.models.decks.formats import FORMATS
from mtg_analyzer.services.bots import BOT_TYPES, bot_catalogue, bots_for_game, run_bots
from mtg_analyzer.services.deck_database import DeckDatabase
from mtg_analyzer.services.game_session import GameActionError, GameSession, GameSessionManager
from mtg_analyzer.services.lazy_card_loader import LazyCardLoader
from mtg_analyzer.services.lobby import Lobby, LobbyError, LobbyGame
from mtg_analyzer.services.replay import serialize_replay

router = APIRouter(prefix="/api/multiplayer", tags=["multiplayer"])


def _authenticate(lobby: Lobby, player_id: Optional[str], ctx: AuthContext) -> None:
    """PLR-9c: lobby/seat ids are public, so naming one proves nothing.

    The verified session account must own ``player_id``. 403 for an unknown id,
    a bot and another account's player alike, so the reply reveals nothing the
    lobby snapshot does not already show. A mismatched request is rejected,
    never silently reassigned to the caller's own player.
    """
    if not lobby.owned_by(player_id, ctx.account.player_uuid):
        raise api_error(403, "player_other_account")


# -- Lobby ---------------------------------------------------------------


@router.post("/connect")
async def connect(
    lobby: Lobby = Depends(get_lobby), ctx: AuthContext = Depends(current_account)
) -> dict[str, Any]:
    """Register the signed-in account's lobby player and get its id back.

    Normally the `/ws/lobby` socket does this on connect; this route is the
    fallback for a client without a socket (and what the tests use). It is
    resolved from the session account only (PLR-9c) and never evicts a live
    socket, so it cannot be used to take over a seat.
    """
    player = _guard(lambda: lobby.connect(ctx.account.player_uuid, ctx.account.name))
    await lobby_connections.broadcast_lobby(lobby)
    return {"player": player.to_dict(), "lobby": lobby.snapshot()}


@router.get("/lobby")
def lobby_snapshot(
    lobby: Lobby = Depends(get_lobby), ctx: AuthContext = Depends(current_account)
) -> dict[str, Any]:
    """Everyone connected and every table, for the Setup screen."""
    return lobby.snapshot()


# -- Setting a game up ---------------------------------------------------


@router.post("/games")
async def create_game(
    request: MultiplayerGameRequest, lobby: Lobby = Depends(get_lobby),
    ctx: AuthContext = Depends(current_account)
) -> dict[str, Any]:
    _authenticate(lobby, request.player_id, ctx)
    game = _guard(lambda: lobby.create(request.player_id, request.name, request.num_players))
    return await _game_response(lobby, game)


@router.post("/games/{game_id}/join")
async def join_game(
    game_id: str, request: MultiplayerPlayerRequest, lobby: Lobby = Depends(get_lobby),
    ctx: AuthContext = Depends(current_account)
) -> dict[str, Any]:
    _authenticate(lobby, request.player_id, ctx)
    game = _guard(lambda: lobby.join(game_id, request.player_id))
    return await _game_response(lobby, game)


@router.post("/games/{game_id}/observe")
async def observe_game(
    game_id: str,
    request: MultiplayerPlayerRequest,
    lobby: Lobby = Depends(get_lobby),
    ctx: AuthContext = Depends(current_account),
    sessions: GameSessionManager = Depends(get_game_session_manager),
) -> dict[str, Any]:
    """Watch a game: the public board, nobody's hand, no actions."""
    _authenticate(lobby, request.player_id, ctx)
    game = _guard(lambda: lobby.observe(game_id, request.player_id))
    return await _game_response(lobby, game, sessions, request.player_id)


@router.post("/games/{game_id}/leave")
async def leave_game(
    game_id: str, request: MultiplayerPlayerRequest, lobby: Lobby = Depends(get_lobby),
    ctx: AuthContext = Depends(current_account)
) -> dict[str, Any]:
    _authenticate(lobby, request.player_id, ctx)
    game = _guard(lambda: lobby.leave(game_id, request.player_id))
    await lobby_connections.broadcast_lobby(lobby)
    if game is not None:
        await lobby_connections.broadcast_game(game, None)
    return {"game": game.to_dict() if game else None, "lobby": lobby.snapshot()}


@router.post("/games/{game_id}/deck")
async def set_deck(
    game_id: str,
    request: MultiplayerDeckRequest,
    lobby: Lobby = Depends(get_lobby),
    decks: DeckDatabase = Depends(get_deck_database),
    ctx: AuthContext = Depends(current_account),
) -> dict[str, Any]:
    """Pick this seat's deck from the decks saved on the server.

    The picking account must be allowed to read the deck (global, or its own private deck;
    for a bot/MCP seat that is the host picking, so host-authorized). The deck is
    snapshotted into the seat (PLR-9b): starting the table never reads the deck store, so
    opponents and the host gain no access to a private deck by sitting at the same table.

    Only legal decks may be chosen, the same rule goldfish enforces
    (`api/game.py`) — checked here, at pick time, so a player finds out
    while they can still change it rather than when the table tries to
    start.
    """
    _authenticate(lobby, request.player_id, ctx)
    deck = decks.get_deck(request.deck_id, ctx.account.player_uuid)
    if deck is None:
        raise api_error(404, "deck_not_found", deck_id=request.deck_id)
    game = _guard(
        lambda: lobby.set_deck(
            game_id, request.player_id, request.deck_id, deck.name, seat_id=request.seat_id,
            deck_snapshot=deck.to_dict(),
        )
    )
    _default_banner_from_deck(lobby, game, request.player_id, request.seat_id, deck)
    return await _game_response(lobby, game)


def _default_banner_from_deck(
    lobby: Lobby, game: LobbyGame, player_id: str, seat_id: Optional[str], deck: Any
) -> None:
    """Fly the deck's colour identity as this seat's banner, unless it has one.

    A seat that has never chosen a banner colour gets the one nobody would
    have to think about: the deck's own (RULE 903.4) colour identity, which
    is exactly what the palette was built to be able to draw. Done here
    rather than in the lobby because the lobby is rules-free and has no idea
    what colours a deck has; done at all because "pick your deck, then also
    pick your colours" is a step nobody wants to take twice.

    An *explicit* pick is never overwritten — swapping decks later keeps the
    banner the player chose. An identity that hasn't been computed yet
    (`None`, unlike an empty list, which is a genuinely colourless deck)
    simply leaves the seat untinted.
    """
    seat = game.seat_for(seat_id or player_id)
    if seat is None or seat.banner_color is not None:
        return
    identity = getattr(deck, "color_identity", None)
    if identity is None:
        return
    _guard(
        lambda: lobby.set_banner_color(
            game.id, player_id, "".join(identity), seat_id=seat_id
        )
    )


@router.post("/games/{game_id}/banner")
async def set_banner_color(
    game_id: str,
    request: MultiplayerBannerColorRequest,
    lobby: Lobby = Depends(get_lobby),
    ctx: AuthContext = Depends(current_account),
) -> dict[str, Any]:
    """Pick the colours this seat's board banner flies (UC4 Setup).

    Cosmetic only, so the key is normalized rather than validated
    (`services/lobby.normalize_banner_color`) and nobody's acceptance is
    cleared by it.
    """
    _authenticate(lobby, request.player_id, ctx)
    game = _guard(
        lambda: lobby.set_banner_color(
            game_id, request.player_id, request.color, seat_id=request.seat_id
        )
    )
    return await _game_response(lobby, game)


# -- Bots ----------------------------------------------------------------


@router.get("/bots")
def list_bots() -> dict[str, Any]:
    """The bot kinds a seat can be filled with (`services/bots.py`)."""
    return {"bots": bot_catalogue()}


@router.post("/games/{game_id}/bots")
async def add_bot(
    game_id: str, request: MultiplayerBotRequest, lobby: Lobby = Depends(get_lobby),
    ctx: AuthContext = Depends(current_account)
) -> dict[str, Any]:
    """Seat a bot. The kind is validated here — the lobby keeps it opaque."""
    _authenticate(lobby, request.player_id, ctx)
    if request.kind not in BOT_TYPES:
        raise api_error(400, "unknown_bot_kind", kind=request.kind)
    name = request.name or BOT_TYPES[request.kind].label
    game = _guard(lambda: lobby.add_bot(game_id, request.player_id, request.kind, name))
    return await _game_response(lobby, game)


def _mcp_launch_hint() -> dict[str, str]:
    """Where the adapter (`backend/mtg_mcp`) can be started from, for the host.

    The MCP client launches it from whatever directory it was opened in, and
    `python -m mtg_mcp` only resolves from `backend/`, so the setup command
    has to carry the interpreter and `PYTHONPATH` explicitly. Prefers the
    project venv (where `requirements-mcp.txt` is installed) over the
    interpreter running the server.
    """
    backend_dir = Path(__file__).resolve().parents[2]
    venv_python = backend_dir / "venv" / "bin" / "python"
    python = venv_python if venv_python.exists() else Path(sys.executable)
    return {"python": str(python), "backend_dir": str(backend_dir)}


@router.post("/games/{game_id}/bots/token")
def mcp_seat_token(
    game_id: str, request: MultiplayerBotRemoveRequest, lobby: Lobby = Depends(get_lobby),
    ctx: AuthContext = Depends(current_account)
) -> dict[str, Any]:
    """An MCP seat's token, for the host to copy into the client (host only).

    Deliberately not part of any lobby snapshot or broadcast: the token is
    the seat's only credential.
    """
    _authenticate(lobby, request.player_id, ctx)
    token = _guard(lambda: lobby.mcp_seat_token(game_id, request.player_id, request.bot_id))
    return {"seat_token": token, **_mcp_launch_hint()}


@router.post("/games/{game_id}/bots/remove")
async def remove_bot(
    game_id: str, request: MultiplayerBotRemoveRequest, lobby: Lobby = Depends(get_lobby),
    ctx: AuthContext = Depends(current_account)
) -> dict[str, Any]:
    _authenticate(lobby, request.player_id, ctx)
    game = _guard(lambda: lobby.remove_bot(game_id, request.player_id, request.bot_id))
    return await _game_response(lobby, game)


@router.post("/games/{game_id}/options")
async def set_options(
    game_id: str, request: MultiplayerOptionsRequest, lobby: Lobby = Depends(get_lobby),
    ctx: AuthContext = Depends(current_account)
) -> dict[str, Any]:
    """Host-only table settings (PLR-13 adds ``gameFormat``/``archenemyId``).

    The format name is validated here rather than in the lobby (which keeps
    every option it stores opaque, same treatment as `mulligan_style`) —
    an unknown name is rejected outright instead of silently falling back
    to Commander, since a rejected *setting* is something the host can fix
    before the table ever starts, unlike a stale saved game.
    """
    _authenticate(lobby, request.player_id, ctx)
    if request.game_format is not None and request.game_format not in FORMATS:
        raise api_error(400, "unknown_format", format=request.game_format)
    game = _guard(
        lambda: lobby.set_options(
            game_id,
            request.player_id,
            request.mulligan_style,
            request.num_players,
            request.takebacks_per_player,
            request.spell_timer_seconds,
            request.randomize_seating,
            request.random_starting_player,
            request.game_format,
            request.archenemy_id,
        )
    )
    return await _game_response(lobby, game)


@router.post("/games/{game_id}/ready")
async def set_ready(
    game_id: str, request: MultiplayerReadyRequest, lobby: Lobby = Depends(get_lobby),
    ctx: AuthContext = Depends(current_account)
) -> dict[str, Any]:
    _authenticate(lobby, request.player_id, ctx)
    game = _guard(lambda: lobby.set_ready(game_id, request.player_id, request.ready))
    return await _game_response(lobby, game)


@router.post("/games/{game_id}/start")
async def start_game(
    game_id: str,
    request: MultiplayerPlayerRequest,
    lobby: Lobby = Depends(get_lobby),
    ctx: AuthContext = Depends(current_account),
    sessions: GameSessionManager = Depends(get_game_session_manager),
    loader: LazyCardLoader = Depends(get_lazy_card_loader),
) -> dict[str, Any]:
    """Every seat has accepted: resolve the decks and start the real game.

    Seat order is turn order. By default that's join order — the host sat
    down first, so they start, RULE 103.2's "decide who goes first" being
    settled by the lobby rather than by a die roll the server arbitrates.
    A table that would rather roll for it turns on `randomize_seating` /
    `random_starting_player`; `LobbyGame.seating_order` applies both, once,
    right here. Whatever it returns *is* the turn order the players then
    see in the board's turn-order strip.
    """
    _authenticate(lobby, request.player_id, ctx)
    game = _guard(lambda: lobby.game(game_id))
    if game.session_id:
        raise api_error(409, "game_already_started")
    if not game.all_ready:
        raise api_error(400, "players_not_accepted")

    seats: list[dict[str, Any]] = []
    for seat in game.seating_order():
        # PLR-9b: the seat's snapshot, not the store (no deck access for the host or opponents).
        snapshot = seat.deck_snapshot
        library, commanders, errors, sideboard = resolve_deck(
            Deck.from_dict(snapshot) if snapshot else None, loader,
            include_sideboard=True, has_id=bool(seat.deck_id),
        )
        if errors:
            raise api_error(
                422, "seat_deck_unplayable", name=seat.name, player_id=seat.player_id, errors=errors
            )
        random.shuffle(library)
        seats.append(
            {
                "player_id": seat.player_id,
                "name": seat.name,
                "library": library,
                "commanders": commanders,
                "sideboard": sideboard,
            }
        )

    session = sessions.create_multiplayer(
        seats,
        mulligan_style=game.mulligan_style,
        takebacks_per_player=game.takebacks_per_player,
        # None here means "use the server default" — resolved in GameSession.
        spell_timer_seconds=game.spell_timer_seconds,
        game_format=game.game_format,
        # RULE 904: the host is the Archenemy unless another seat was
        # explicitly picked — `Lobby` stores `None` for "not chosen", the
        # same convention `build_multiplayer_engine`/`_setup_variants`
        # already fall back on via `state.players[0]`, but the *lobby's*
        # seat order (join order) and the engine's `seating_order()` (which
        # `randomize_seating` may have reshuffled) aren't the same list, so
        # the default is resolved here against the host explicitly instead.
        archenemy_id=game.archenemy_id or game.host_id,
    )
    game = _guard(lambda: lobby.start(game_id, session.id))
    # Bots keep their opening hands (and, if one is on the play, take their
    # first turn) before anybody is shown the table — otherwise the humans
    # would sit in the mulligan screen waiting on a seat that has no client
    # to click "Behalten".
    run_bots(session, bots_for_game(game))
    return await _game_response(lobby, game, sessions, request.player_id)


# -- Playing -------------------------------------------------------------


@router.get("/games/{game_id}")
def game_view(
    game_id: str,
    player_id: str,
    lobby: Lobby = Depends(get_lobby),
    ctx: AuthContext = Depends(current_account),
    sessions: GameSessionManager = Depends(get_game_session_manager),
) -> dict[str, Any]:
    """This player's own view of the game (a seat's, or an observer's)."""
    _authenticate(lobby, player_id, ctx)
    game = _guard(lambda: lobby.game(game_id))
    return {"game": game.to_dict(), "view": _view_for(game, sessions, player_id)}


@router.post("/games/{game_id}/action")
async def apply_action(
    game_id: str,
    request: MultiplayerActionRequest,
    lobby: Lobby = Depends(get_lobby),
    ctx: AuthContext = Depends(current_account),
    sessions: GameSessionManager = Depends(get_game_session_manager),
) -> dict[str, Any]:
    """Apply one action *as* ``player_id``.

    The seat is taken from the request rather than from the action body, so
    a client can only ever act for itself; the engine then decides whether
    that player may actually do it right now (RULE 601.3a timing and the
    rest), which is what stops the non-active player from, say, playing a
    land on someone else's turn.
    """
    _authenticate(lobby, request.player_id, ctx)
    game = _guard(lambda: lobby.game(game_id))
    session = _require_session(game, sessions)
    if game.seat_for(request.player_id) is None:
        raise api_error(403, "observers_cannot_act")
    # Acting is what proves a client is still there — the idle watchdog
    # (`api/multiplayer_ws.sweep_once`) measures silence from here.
    lobby.touch(request.player_id)
    try:
        session.apply_action(request.action, actor_id=request.player_id)
    except GameActionError as exc:
        raise error_from(exc, 400) from exc
    if request.action.get("type") == "emote":
        # A conversation update must not drive bot moves or advance priority.
        await lobby_connections.broadcast_game(game, session)
        return {"game": game.to_dict(), "view": session.view(perspective=request.player_id)}
    return await _after_move(lobby, game, session, request.player_id)


@router.post("/games/{game_id}/concede")
async def concede(
    game_id: str,
    request: MultiplayerPlayerRequest,
    lobby: Lobby = Depends(get_lobby),
    ctx: AuthContext = Depends(current_account),
    sessions: GameSessionManager = Depends(get_game_session_manager),
) -> dict[str, Any]:
    """RULE 104.3a: leave the game. Legal at any time, from any seat."""
    _authenticate(lobby, request.player_id, ctx)
    game = _guard(lambda: lobby.game(game_id))
    session = _require_session(game, sessions)
    if game.seat_for(request.player_id) is None:
        raise api_error(403, "no_seat_in_game")
    try:
        session.concede(request.player_id)
    except GameActionError as exc:
        raise error_from(exc, 400) from exc
    _guard(lambda: lobby.record_concession(game_id, request.player_id))
    return await _after_move(lobby, game, session, request.player_id)


@router.post("/games/{game_id}/takeback")
async def take_back(
    game_id: str,
    request: MultiplayerPlayerRequest,
    lobby: Lobby = Depends(get_lobby),
    ctx: AuthContext = Depends(current_account),
    sessions: GameSessionManager = Depends(get_game_session_manager),
) -> dict[str, Any]:
    """Undo back through ``player_id``'s own last move (UC4 Setup).

    A per-seat, table-configured convenience (`GameSession.take_back`), not
    a RULE 117 action — legal regardless of who currently holds priority,
    the same way conceding is, since a misclick doesn't wait for a
    convenient moment.
    """
    _authenticate(lobby, request.player_id, ctx)
    game = _guard(lambda: lobby.game(game_id))
    session = _require_session(game, sessions)
    if game.seat_for(request.player_id) is None:
        raise api_error(403, "no_seat_in_game")
    try:
        session.take_back(request.player_id)
    except GameActionError as exc:
        raise error_from(exc, 400) from exc
    return await _after_move(lobby, game, session, request.player_id)


@router.post("/games/{game_id}/ui-draft")
def save_ui_draft(
    game_id: str,
    request: MultiplayerUiDraftRequest,
    lobby: Lobby = Depends(get_lobby),
    ctx: AuthContext = Depends(current_account),
    sessions: GameSessionManager = Depends(get_game_session_manager),
) -> dict[str, Any]:
    """PLR-6: store (or clear) a seated player's in-progress UI selection.

    Quiet, like the goldfish route: never broadcasts. Seat-checked so a
    spectator or stranger can't write another seat's draft (BUG-38).
    """
    _authenticate(lobby, request.player_id, ctx)
    game = _guard(lambda: lobby.game(game_id))
    session = _require_session(game, sessions)
    if game.seat_for(request.player_id) is None:
        raise api_error(403, "no_seat_in_game")
    try:
        session.set_ui_draft(request.player_id, request.draft)
    except GameActionError as exc:
        raise error_from(exc, 400) from exc
    return {"ok": True}


@router.get("/games/{game_id}/replay-export")
def export_replay(
    game_id: str,
    player_id: str,
    lobby: Lobby = Depends(get_lobby),
    ctx: AuthContext = Depends(current_account),
    sessions: GameSessionManager = Depends(get_game_session_manager),
) -> dict[str, Any]:
    """Replay descriptor of a finished game, for a player who sat at it.

    The descriptor serializes every zone, libraries in order, so mid-game it
    would hand a seat its opponents' hidden information (RULE 400.2); it is
    therefore refused until the game is over (BUG-38).
    """
    _authenticate(lobby, player_id, ctx)
    game = _guard(lambda: lobby.game(game_id))
    session = _require_session(game, sessions)
    if game.seat_for(player_id) is None:
        raise api_error(403, "no_seat_in_game")
    if not session.engine.state.game_over:
        raise api_error(409, "replay_not_finished")
    return serialize_replay(session.engine.state)


# -- Shared helpers ------------------------------------------------------


async def _after_move(
    lobby: Lobby, game: LobbyGame, session: GameSession, player_id: str
) -> dict[str, Any]:
    """Let the bots answer, push the position, close the table if it's over.

    The bots run *before* the broadcast on purpose: a human's move and
    every bot response it provokes are one state change as far as the
    clients are concerned, which is both fewer pushes and a board that
    never shows a half-finished bot turn.
    """
    run_bots(session, bots_for_game(game))
    if session.engine.state.game_over:
        _guard(lambda: lobby.finish(game.id))
    await lobby_connections.broadcast_game(game, session)
    await lobby_connections.broadcast_lobby(lobby)
    return {"game": game.to_dict(), "view": session.view(perspective=player_id)}


def _view_for(
    game: LobbyGame, sessions: GameSessionManager, player_id: str
) -> Optional[dict[str, Any]]:
    """The redacted view ``player_id`` is entitled to, or None before start."""
    if not game.session_id:
        return None
    try:
        session = sessions.get(game.session_id)
    except KeyError:
        return None
    if game.seat_for(player_id) is not None:
        return session.view(perspective=player_id)
    return session.observer_view()


def _require_session(game: LobbyGame, sessions: GameSessionManager) -> GameSession:
    if not game.session_id:
        raise api_error(409, "game_not_started")
    try:
        return sessions.get(game.session_id)
    except KeyError as exc:
        raise api_error(404, "game_session_expired") from exc


async def _game_response(
    lobby: Lobby,
    game: LobbyGame,
    sessions: Optional[GameSessionManager] = None,
    player_id: Optional[str] = None,
) -> dict[str, Any]:
    """Broadcast a table change, and return it to the caller as well."""
    session = None
    if sessions is not None and game.session_id:
        try:
            session = sessions.get(game.session_id)
        except KeyError:
            session = None
    await lobby_connections.broadcast_lobby(lobby)
    await lobby_connections.broadcast_game(game, session)
    view = _view_for(game, sessions, player_id) if sessions and player_id else None
    return {"game": game.to_dict(), "lobby": lobby.snapshot(), "view": view}


def _guard(fn):
    """Run a lobby call, turning its `LobbyError` into a 400."""
    try:
        return fn()
    except LobbyError as exc:
        raise error_from(exc, 400) from exc
