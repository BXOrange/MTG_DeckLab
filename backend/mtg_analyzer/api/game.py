"""Game session endpoints: start a goldfish game, act, rewind, restart (UC3).

Reference: docs/02_MVP_USECASES_REVISED.md UC3/UC4,
backend/ToDo_Backend.md "Game Engine".

Turns the rules/game engine (mtg_analyzer/game/) into a playable
server-held session (mtg_analyzer/services/game_session.py):

* ``POST /api/game/goldfish``       — start a solo game from a saved deck
                                      or decklist text; deals the opening
                                      hand and returns the initial view.
* ``GET  /api/game/{id}``           — current state + legal actions.
* ``POST /api/game/{id}/action``    — apply one action (snapshotted for undo).
* ``POST /api/game/{id}/rewind``    — undo the last move(s).
* ``POST /api/game/{id}/restart``   — reset to the opening state.
* ``DELETE /api/game/{id}``         — drop the session.
* ``POST /api/game/multiplayer``    — stub (501): interactive multiplayer
                                      isn't implemented yet (UC4).

This is the REST control surface; the existing ``/ws/game/{id}`` WebSocket
(api/game_ws.py) is still a transport-only relay and not yet fed by these
sessions (see ToDo "Not yet wired").
"""

from __future__ import annotations

import random

from fastapi import APIRouter, Depends, HTTPException

from mtg_analyzer.api.dependencies import (
    get_deck_database,
    get_game_session_manager,
    get_lazy_card_loader,
)
from mtg_analyzer.api.schemas import GameActionRequest, RewindRequest, StartGoldfishRequest
from mtg_analyzer.models.card import Card
from mtg_analyzer.parser.deckliste_parser import parse_deck_sections
from mtg_analyzer.services.deck_database import DeckDatabase
from mtg_analyzer.services.deck_validation import apply_legality
from mtg_analyzer.services.game_session import (
    GameActionError,
    GameSessionManager,
    MultiplayerNotImplementedError,
)
from mtg_analyzer.services.lazy_card_loader import LazyCardLoader

router = APIRouter(prefix="/api/game", tags=["game"])


def _expand(entries, cards_by_name: dict[str, Card]) -> tuple[list[Card], list[str]]:
    """Expand ``(name, qty)`` entries into a flat Card list + missing names."""
    expanded: list[Card] = []
    missing: list[str] = []
    for entry in entries:
        card = cards_by_name.get(entry.name)
        if card is None:
            missing.append(entry.name)
            continue
        expanded.extend([card] * entry.qty)
    return expanded, missing


@router.post("/goldfish")
def start_goldfish(
    request: StartGoldfishRequest,
    sessions: GameSessionManager = Depends(get_game_session_manager),
    decks: DeckDatabase = Depends(get_deck_database),
    loader: LazyCardLoader = Depends(get_lazy_card_loader),
) -> dict[str, object]:
    """Start a solo goldfish game from a saved deck or decklist text."""
    commander_text = request.commander_text
    mainboard_text = request.mainboard_text
    sideboard_text = request.sideboard_text

    if request.deck_id:
        deck = decks.get_deck(request.deck_id)
        if deck is None:
            raise HTTPException(404, f'No saved deck with id "{request.deck_id}"')
        commander_text = deck.commander_text
        mainboard_text = deck.mainboard_text
        sideboard_text = deck.sideboard_text

    parsed = parse_deck_sections(commander_text, mainboard_text, sideboard_text)
    resolved = loader.load_cards(
        [e.name for e in parsed.commanders] + [e.name for e in parsed.all_cards]
    )
    apply_legality(parsed, resolved)

    library, missing_lib = _expand(parsed.main_deck, resolved.cards)
    commanders, missing_cmd = _expand(parsed.commanders, resolved.cards)
    missing = sorted(set(missing_lib) | set(missing_cmd) | set(resolved.not_found))

    # Only legal decks may start a goldfish game (docs/02 UC3, this file's
    # module docstring). Enforced here as well as in the UI so the rule
    # can't be bypassed by calling the API directly.
    if not parsed.validation.is_legal:
        raise HTTPException(
            422,
            {
                "message": "Deck ist nicht legal – nur legale Decks können ein Goldfisch-Spiel starten.",
                "errors": parsed.validation.errors,
                "validation": parsed.validation.to_dict(),
                "notFound": missing,
            },
        )

    # A deck can pass structural legality yet resolve to nothing (its cards
    # aren't in the cache and Scryfall didn't find them) — can't play that.
    if not library and not commanders:
        raise HTTPException(
            422,
            {"message": "Deck hat keine auflösbaren Karten.", "notFound": missing},
        )

    if request.shuffle:
        random.shuffle(library)

    session = sessions.create_goldfish(
        library=library,
        commanders=commanders,
        starting_life=request.starting_life,
        starting_hand=request.starting_hand,
    )
    view = session.view()
    view["notFound"] = sorted(set(missing) | set(resolved.not_found))
    return view


@router.post("/multiplayer", status_code=501)
def start_multiplayer(
    sessions: GameSessionManager = Depends(get_game_session_manager),
) -> dict[str, object]:
    """Stub: interactive multiplayer isn't implemented yet (UC4)."""
    try:
        sessions.create_multiplayer()
    except MultiplayerNotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    return {}  # unreachable


@router.get("/{session_id}")
def get_session(
    session_id: str, sessions: GameSessionManager = Depends(get_game_session_manager)
) -> dict[str, object]:
    return _session(sessions, session_id).view()


@router.post("/{session_id}/action")
def apply_action(
    session_id: str,
    request: GameActionRequest,
    sessions: GameSessionManager = Depends(get_game_session_manager),
) -> dict[str, object]:
    session = _session(sessions, session_id)
    try:
        return session.apply_action(request.model_dump())
    except GameActionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{session_id}/rewind")
def rewind(
    session_id: str,
    request: RewindRequest = RewindRequest(),
    sessions: GameSessionManager = Depends(get_game_session_manager),
) -> dict[str, object]:
    session = _session(sessions, session_id)
    try:
        return session.rewind(request.steps)
    except GameActionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{session_id}/restart")
def restart(
    session_id: str, sessions: GameSessionManager = Depends(get_game_session_manager)
) -> dict[str, object]:
    return _session(sessions, session_id).restart()


@router.delete("/{session_id}")
def delete_session(
    session_id: str, sessions: GameSessionManager = Depends(get_game_session_manager)
) -> dict[str, object]:
    if not sessions.remove(session_id):
        raise HTTPException(status_code=404, detail=f'No game session "{session_id}"')
    return {"deleted": True}


def _session(sessions: GameSessionManager, session_id: str):
    try:
        return sessions.get(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f'No game session "{session_id}"') from exc
