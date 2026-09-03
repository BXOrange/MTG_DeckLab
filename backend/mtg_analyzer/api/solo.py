"""Solo-vs-bots endpoints: play a saved deck against 1-3 bots (PLR-14).

The Multiplayer engine without the lobby. `api/multiplayer.py` gives a real
N-player `GameEngine` — genuine turns, RULE 117 priority played out, every
seat's hidden zones redacted server-side (RULE 400.2) — but only reachable
through `services/lobby.py` (presence, a WebSocket, table setup, other
humans). This module is the same game with the lobby stripped out: one
human seat (`SOLO_HUMAN_ID`), 1-3 bot seats (`services/bots.py`), and a
plain REST surface like goldfish's `api/game.py`.

* ``POST /api/solo/start``            — resolve the decks, build the session,
                                       let the bots keep their hands, return
                                       the human's first view.
* ``POST /api/solo/{id}/action``      — one action as the human, then the
                                       bots answer.
* ``POST /api/solo/{id}/concede``     — RULE 104.3a.
* ``POST /api/solo/{id}/restart``     — reset to the opening state.
* ``GET  /api/solo/{id}``             — the human's current view (reconnect).
* ``DELETE /api/solo/{id}``           — drop the session.

The bot roster lives on the session (``session._solo_bots``, the same
stash idiom `create_replay` uses for its card loader) so it survives across
requests and a `restart`. Bots run *synchronously* after every human action
(`_advance_solo_bots`) — no background task: a bounded `run_bots` loop
carries the game to the next point the human has something to decide.
"""

from __future__ import annotations

import random
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from mtg_analyzer.api.dependencies import (
    get_deck_database,
    get_game_session_manager,
    get_lazy_card_loader,
)
from mtg_analyzer.api.game import resolve_seat_deck
from mtg_analyzer.api.schemas import GameActionRequest, SoloStartRequest
from mtg_analyzer.models.game_format import FORMATS
from mtg_analyzer.services.bots import BOT_ID_PREFIX, BOT_TYPES, create_bot, run_bots
from mtg_analyzer.services.deck_database import DeckDatabase
from mtg_analyzer.services.game_session import GameActionError, GameSession, GameSessionManager
from mtg_analyzer.services.lazy_card_loader import LazyCardLoader

router = APIRouter(prefix="/api/solo", tags=["solo"])

#: The one human seat's player id. Not a `bot:` id, and distinct enough that
#: nothing mistakes it for a lobby-issued one.
SOLO_HUMAN_ID = "solo:you"

#: How many times `_advance_solo_bots` may re-invoke `run_bots` after it
#: yields at its own 200-action cap without the human getting a turn — a
#: guard against a bot loop, never hit in normal play (one bot turn is a
#: few dozen actions).
SOLO_BOT_ADVANCE_ROUNDS = 20

#: Solo seats 1 human + 1..MAX_BOTS bots (the engine itself is N-player;
#: this matches Multiplayer's readable ceiling of four seats).
MAX_BOTS = 3


@router.post("/start")
def start(
    request: SoloStartRequest,
    sessions: GameSessionManager = Depends(get_game_session_manager),
    decks: DeckDatabase = Depends(get_deck_database),
    loader: LazyCardLoader = Depends(get_lazy_card_loader),
) -> dict[str, Any]:
    """Resolve the human + bot decks and start the game."""
    opponents = list(request.opponents or [])
    if not 1 <= len(opponents) <= MAX_BOTS:
        raise HTTPException(400, f"a solo game needs 1 to {MAX_BOTS} bot opponents")
    if request.game_format is not None and request.game_format not in FORMATS:
        raise HTTPException(400, f'Unknown format "{request.game_format}"')
    for opp in opponents:
        if opp.kind not in BOT_TYPES:
            raise HTTPException(400, f'Unknown bot kind "{opp.kind}"')

    # (player_id, deck_id, bot_kind or None, display name) — human first.
    plan: list[tuple[str, str, Any, str]] = [(SOLO_HUMAN_ID, request.deck_id, None, "Du")]
    for i, opp in enumerate(opponents, start=1):
        plan.append(
            (f"{BOT_ID_PREFIX}{i}", opp.deck_id, opp.kind, f"{BOT_TYPES[opp.kind].label} {i}")
        )

    seats: list[dict[str, Any]] = []
    for player_id, deck_id, _kind, name in plan:
        library, commanders, errors = resolve_seat_deck(deck_id, decks, loader)
        if errors:
            who = "Dein Deck" if player_id == SOLO_HUMAN_ID else f'Das Deck von "{name}"'
            raise HTTPException(
                422,
                {"message": f"{who} kann nicht gespielt werden.", "player_id": player_id,
                 "errors": errors},
            )
        random.shuffle(library)
        seats.append(
            {"player_id": player_id, "name": name, "library": library, "commanders": commanders}
        )

    # RULE 103.2: seat order is turn order; the first seat is on the play.
    # "you" keeps the human there (goldfish's default); "random" rolls for it.
    if request.starting_player == "random":
        random.shuffle(seats)

    session = sessions.create_multiplayer(
        seats, mulligan_style=request.mulligan_style, game_format=request.game_format
    )
    session._solo_bots = {
        player_id: create_bot(kind, player_id, name)
        for player_id, _deck, kind, name in plan
        if kind is not None
    }
    # Bots keep their opening hands (and, if one is on the play, take their
    # first turn) before the human is shown the mulligan screen — otherwise
    # they'd sit there with no client to click "Behalten". Same reason
    # `api/multiplayer.start_game` runs the bots right after `lobby.start`.
    run_bots(session, session._solo_bots)

    view = session.view(perspective=SOLO_HUMAN_ID)
    view["notFound"] = []  # resolve_seat_deck 422s on anything unresolvable
    return view


@router.get("/{session_id}")
def get_view(
    session_id: str, sessions: GameSessionManager = Depends(get_game_session_manager)
) -> dict[str, Any]:
    """The human's current (redacted) view — for a reload / tab re-open."""
    return _session(sessions, session_id).view(perspective=SOLO_HUMAN_ID)


@router.post("/{session_id}/action")
def apply_action(
    session_id: str,
    request: GameActionRequest,
    sessions: GameSessionManager = Depends(get_game_session_manager),
) -> dict[str, Any]:
    """Apply one action as the human, then let the bots answer it."""
    session = _session(sessions, session_id)
    try:
        session.apply_action(request.model_dump(), actor_id=SOLO_HUMAN_ID)
    except GameActionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _advance_solo_bots(session)


@router.post("/{session_id}/concede")
def concede(
    session_id: str, sessions: GameSessionManager = Depends(get_game_session_manager)
) -> dict[str, Any]:
    """RULE 104.3a: the human leaves the game."""
    session = _session(sessions, session_id)
    try:
        session.concede(SOLO_HUMAN_ID)
    except GameActionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _advance_solo_bots(session)


@router.post("/{session_id}/restart")
def restart(
    session_id: str, sessions: GameSessionManager = Depends(get_game_session_manager)
) -> dict[str, Any]:
    """Reset to the opening state (UC3's "jederzeit neu starten"), then let
    the bots keep their opening hands again."""
    session = _session(sessions, session_id)
    session.restart()
    run_bots(session, getattr(session, "_solo_bots", {}))
    return session.view(perspective=SOLO_HUMAN_ID)


@router.delete("/{session_id}")
def delete_session(
    session_id: str, sessions: GameSessionManager = Depends(get_game_session_manager)
) -> dict[str, Any]:
    if not sessions.remove(session_id):
        raise HTTPException(status_code=404, detail=f'No solo session "{session_id}"')
    return {"deleted": True}


def _advance_solo_bots(session: GameSession) -> dict[str, Any]:
    """Run the bots until the human has something to decide (priority, a
    pending choice, a block) or the game is over, then return the human's
    view.

    `run_bots` already drains up to `MAX_BOT_ACTIONS` per call and stops the
    moment the human holds priority (it never acts for a non-bot seat), so
    one call is almost always enough; the loop only matters if a single bot
    turn is long enough to hit that cap.
    """
    for _ in range(SOLO_BOT_ADVANCE_ROUNDS):
        if session.engine.state.game_over:
            break
        moved = run_bots(session, getattr(session, "_solo_bots", {}))
        if not moved:
            break
        if session.legal_actions(perspective=SOLO_HUMAN_ID):
            break
    return session.view(perspective=SOLO_HUMAN_ID)


def _session(sessions: GameSessionManager, session_id: str) -> GameSession:
    try:
        return sessions.get(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f'No solo session "{session_id}"') from exc
