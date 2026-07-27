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
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException

from mtg_analyzer.api.dependencies import (
    get_deck_database,
    get_game_session_manager,
    get_lazy_card_loader,
    get_lobby,
)
from mtg_analyzer.api.game import expand_entries
from mtg_analyzer.api.multiplayer_ws import manager as lobby_connections
from mtg_analyzer.api.schemas import (
    LobbyConnectRequest,
    MultiplayerActionRequest,
    MultiplayerBotRemoveRequest,
    MultiplayerBotRequest,
    MultiplayerDeckRequest,
    MultiplayerGameRequest,
    MultiplayerOptionsRequest,
    MultiplayerPlayerRequest,
    MultiplayerReadyRequest,
)
from mtg_analyzer.parser.deckliste_parser import parse_deck_sections
from mtg_analyzer.services.bots import BOT_TYPES, bot_catalogue, bots_for_game, run_bots
from mtg_analyzer.services.deck_database import DeckDatabase
from mtg_analyzer.services.deck_validation import apply_legality
from mtg_analyzer.services.game_session import GameActionError, GameSession, GameSessionManager
from mtg_analyzer.services.lazy_card_loader import LazyCardLoader
from mtg_analyzer.services.lobby import Lobby, LobbyError, LobbyGame

router = APIRouter(prefix="/api/multiplayer", tags=["multiplayer"])


# -- Lobby ---------------------------------------------------------------


@router.post("/connect")
async def connect(
    request: LobbyConnectRequest, lobby: Lobby = Depends(get_lobby)
) -> dict[str, Any]:
    """Register a player and get their id back.

    Normally the `/ws/lobby` socket does this on connect; this route is the
    fallback for a client without a socket (and what the tests use).
    """
    player = lobby.connect(name=request.name, player_id=request.player_id)
    await lobby_connections.broadcast_lobby(lobby)
    return {"player": player.to_dict(), "lobby": lobby.snapshot()}


@router.get("/lobby")
def lobby_snapshot(lobby: Lobby = Depends(get_lobby)) -> dict[str, Any]:
    """Everyone connected and every table, for the Setup screen."""
    return lobby.snapshot()


# -- Setting a game up ---------------------------------------------------


@router.post("/games")
async def create_game(
    request: MultiplayerGameRequest, lobby: Lobby = Depends(get_lobby)
) -> dict[str, Any]:
    game = _guard(lambda: lobby.create(request.player_id, request.name, request.num_players))
    return await _game_response(lobby, game)


@router.post("/games/{game_id}/join")
async def join_game(
    game_id: str, request: MultiplayerPlayerRequest, lobby: Lobby = Depends(get_lobby)
) -> dict[str, Any]:
    game = _guard(lambda: lobby.join(game_id, request.player_id))
    return await _game_response(lobby, game)


@router.post("/games/{game_id}/observe")
async def observe_game(
    game_id: str,
    request: MultiplayerPlayerRequest,
    lobby: Lobby = Depends(get_lobby),
    sessions: GameSessionManager = Depends(get_game_session_manager),
) -> dict[str, Any]:
    """Watch a game: the public board, nobody's hand, no actions."""
    game = _guard(lambda: lobby.observe(game_id, request.player_id))
    return await _game_response(lobby, game, sessions, request.player_id)


@router.post("/games/{game_id}/leave")
async def leave_game(
    game_id: str, request: MultiplayerPlayerRequest, lobby: Lobby = Depends(get_lobby)
) -> dict[str, Any]:
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
) -> dict[str, Any]:
    """Pick this seat's deck from the decks saved on the server.

    Only legal decks may be chosen, the same rule goldfish enforces
    (`api/game.py`) — checked here, at pick time, so a player finds out
    while they can still change it rather than when the table tries to
    start.
    """
    deck = decks.get_deck(request.deck_id)
    if deck is None:
        raise HTTPException(404, f'No saved deck with id "{request.deck_id}"')
    game = _guard(
        lambda: lobby.set_deck(
            game_id, request.player_id, request.deck_id, deck.name, seat_id=request.seat_id
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
    game_id: str, request: MultiplayerBotRequest, lobby: Lobby = Depends(get_lobby)
) -> dict[str, Any]:
    """Seat a bot. The kind is validated here — the lobby keeps it opaque."""
    if request.kind not in BOT_TYPES:
        raise HTTPException(400, f'Unknown bot kind "{request.kind}"')
    name = request.name or BOT_TYPES[request.kind].label
    game = _guard(lambda: lobby.add_bot(game_id, request.player_id, request.kind, name))
    return await _game_response(lobby, game)


@router.post("/games/{game_id}/bots/remove")
async def remove_bot(
    game_id: str, request: MultiplayerBotRemoveRequest, lobby: Lobby = Depends(get_lobby)
) -> dict[str, Any]:
    game = _guard(lambda: lobby.remove_bot(game_id, request.player_id, request.bot_id))
    return await _game_response(lobby, game)


@router.post("/games/{game_id}/options")
async def set_options(
    game_id: str, request: MultiplayerOptionsRequest, lobby: Lobby = Depends(get_lobby)
) -> dict[str, Any]:
    game = _guard(
        lambda: lobby.set_options(
            game_id,
            request.player_id,
            request.mulligan_style,
            request.num_players,
            request.takebacks_per_player,
        )
    )
    return await _game_response(lobby, game)


@router.post("/games/{game_id}/ready")
async def set_ready(
    game_id: str, request: MultiplayerReadyRequest, lobby: Lobby = Depends(get_lobby)
) -> dict[str, Any]:
    game = _guard(lambda: lobby.set_ready(game_id, request.player_id, request.ready))
    return await _game_response(lobby, game)


@router.post("/games/{game_id}/start")
async def start_game(
    game_id: str,
    request: MultiplayerPlayerRequest,
    lobby: Lobby = Depends(get_lobby),
    sessions: GameSessionManager = Depends(get_game_session_manager),
    decks: DeckDatabase = Depends(get_deck_database),
    loader: LazyCardLoader = Depends(get_lazy_card_loader),
) -> dict[str, Any]:
    """Every seat has accepted: resolve the decks and start the real game.

    Seat order is turn order (the host sat down first, so they start —
    RULE 103.2's "decide who goes first" is settled by the lobby rather
    than by a die roll the server would have to arbitrate).
    """
    game = _guard(lambda: lobby.game(game_id))
    if game.session_id:
        raise HTTPException(409, "this game has already started")
    if not game.all_ready:
        raise HTTPException(400, "not every player has accepted yet")

    seats: list[dict[str, Any]] = []
    for seat in game.seats:
        library, commanders, errors = _resolve_seat_deck(seat.deck_id, decks, loader)
        if errors:
            raise HTTPException(
                422,
                {
                    "message": f'Deck von "{seat.name}" kann nicht gespielt werden.',
                    "player_id": seat.player_id,
                    "errors": errors,
                },
            )
        random.shuffle(library)
        seats.append(
            {
                "player_id": seat.player_id,
                "name": seat.name,
                "library": library,
                "commanders": commanders,
            }
        )

    session = sessions.create_multiplayer(
        seats, mulligan_style=game.mulligan_style, takebacks_per_player=game.takebacks_per_player
    )
    game = _guard(lambda: lobby.start(game_id, session.id))
    # Bots keep their opening hands (and, if one is on the play, take their
    # first turn) before anybody is shown the table — otherwise the humans
    # would sit in the mulligan screen waiting on a seat that has no client
    # to click "Behalten".
    run_bots(session, bots_for_game(game))
    return await _game_response(lobby, game, sessions, request.player_id)


def _resolve_seat_deck(
    deck_id: Optional[str], decks: DeckDatabase, loader: LazyCardLoader
) -> tuple[list[Any], list[Any], list[str]]:
    """One seat's saved deck → (library, commanders, blocking errors).

    Mirrors `api/game.py`'s goldfish resolution exactly: parse the saved
    sections, resolve the names, apply Commander legality, and refuse
    anything illegal or unresolvable — a multiplayer game is a real game,
    so the same gate applies.
    """
    if not deck_id:
        return [], [], ["Kein Deck ausgewählt."]
    deck = decks.get_deck(deck_id)
    if deck is None:
        return [], [], ["Deck existiert nicht mehr."]
    parsed = parse_deck_sections(deck.commander_text, deck.mainboard_text, deck.sideboard_text)
    resolved = loader.load_cards(
        [e.name for e in parsed.commanders] + [e.name for e in parsed.all_cards]
    )
    apply_legality(parsed, resolved)
    library, missing_lib = expand_entries(parsed.main_deck, resolved.cards)
    commanders, missing_cmd = expand_entries(parsed.commanders, resolved.cards)
    if not parsed.validation.is_legal:
        return [], [], list(parsed.validation.errors)
    if not library and not commanders:
        missing = sorted(set(missing_lib) | set(missing_cmd))
        return [], [], [f"Keine auflösbaren Karten: {', '.join(missing) or '—'}"]
    return library, commanders, []


# -- Playing -------------------------------------------------------------


@router.get("/games/{game_id}")
def game_view(
    game_id: str,
    player_id: str,
    lobby: Lobby = Depends(get_lobby),
    sessions: GameSessionManager = Depends(get_game_session_manager),
) -> dict[str, Any]:
    """This player's own view of the game (a seat's, or an observer's)."""
    game = _guard(lambda: lobby.game(game_id))
    return {"game": game.to_dict(), "view": _view_for(game, sessions, player_id)}


@router.post("/games/{game_id}/action")
async def apply_action(
    game_id: str,
    request: MultiplayerActionRequest,
    lobby: Lobby = Depends(get_lobby),
    sessions: GameSessionManager = Depends(get_game_session_manager),
) -> dict[str, Any]:
    """Apply one action *as* ``player_id``.

    The seat is taken from the request rather than from the action body, so
    a client can only ever act for itself; the engine then decides whether
    that player may actually do it right now (RULE 601.3a timing and the
    rest), which is what stops the non-active player from, say, playing a
    land on someone else's turn.
    """
    game = _guard(lambda: lobby.game(game_id))
    session = _require_session(game, sessions)
    if game.seat_for(request.player_id) is None:
        raise HTTPException(403, "observers can watch but not act")
    # Acting is what proves a client is still there — the idle watchdog
    # (`api/multiplayer_ws.sweep_once`) measures silence from here.
    lobby.touch(request.player_id)
    try:
        session.apply_action(request.action, actor_id=request.player_id)
    except GameActionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await _after_move(lobby, game, session, request.player_id)


@router.post("/games/{game_id}/concede")
async def concede(
    game_id: str,
    request: MultiplayerPlayerRequest,
    lobby: Lobby = Depends(get_lobby),
    sessions: GameSessionManager = Depends(get_game_session_manager),
) -> dict[str, Any]:
    """RULE 104.3a: leave the game. Legal at any time, from any seat."""
    game = _guard(lambda: lobby.game(game_id))
    session = _require_session(game, sessions)
    if game.seat_for(request.player_id) is None:
        raise HTTPException(403, "you have no seat in this game")
    try:
        session.concede(request.player_id)
    except GameActionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _guard(lambda: lobby.record_concession(game_id, request.player_id))
    return await _after_move(lobby, game, session, request.player_id)


@router.post("/games/{game_id}/takeback")
async def take_back(
    game_id: str,
    request: MultiplayerPlayerRequest,
    lobby: Lobby = Depends(get_lobby),
    sessions: GameSessionManager = Depends(get_game_session_manager),
) -> dict[str, Any]:
    """Undo back through ``player_id``'s own last move (UC4 Setup).

    A per-seat, table-configured convenience (`GameSession.take_back`), not
    a RULE 117 action — legal regardless of who currently holds priority,
    the same way conceding is, since a misclick doesn't wait for a
    convenient moment.
    """
    game = _guard(lambda: lobby.game(game_id))
    session = _require_session(game, sessions)
    if game.seat_for(request.player_id) is None:
        raise HTTPException(403, "you have no seat in this game")
    try:
        session.take_back(request.player_id)
    except GameActionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await _after_move(lobby, game, session, request.player_id)


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
        raise HTTPException(409, "this game hasn't started yet")
    try:
        return sessions.get(game.session_id)
    except KeyError as exc:
        raise HTTPException(404, "the game session has expired") from exc


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
        raise HTTPException(status_code=400, detail=str(exc)) from exc
