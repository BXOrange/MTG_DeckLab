"""Game session endpoints: start a goldfish game, act, rewind, restart (UC3).

Reference: docs/requirements/02_MVP_USECASES_REVISED.md UC3/UC4,
docs/implementation-state/Done_Backend.md "Game Engine".

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
from mtg_analyzer.api.schemas import (
    DeckTokensRequest,
    GameActionRequest,
    RewindRequest,
    SaveUiDraftRequest,
    StartGoldfishRequest,
    StartReplayRequest,
)
from mtg_analyzer.models.card import Card
from mtg_analyzer.parser.deckliste_parser import parse_deck_sections
from mtg_analyzer.services.deck_database import DeckDatabase
from mtg_analyzer.services.deck_tokens import producible_tokens
from mtg_analyzer.services.deck_validation import apply_legality
from mtg_analyzer.services.game_session import (
    GameActionError,
    GameSessionManager,
    MultiplayerNotImplementedError,
)
from mtg_analyzer.services.lazy_card_loader import LazyCardLoader
from mtg_analyzer.services.replay import blank_replay, serialize_replay

router = APIRouter(prefix="/api/game", tags=["game"])


def expand_entries(entries, cards_by_name: dict[str, Card]) -> tuple[list[Card], list[str]]:
    """Expand ``(name, qty)`` entries into a flat Card list + missing names.

    Public because `api/multiplayer.py` / `api/solo.py` resolve a seat's deck
    exactly the same way this module resolves a goldfish deck.
    """
    expanded: list[Card] = []
    missing: list[str] = []
    for entry in entries:
        card = cards_by_name.get(entry.name)
        if card is None:
            missing.append(entry.name)
            continue
        expanded.extend([card] * entry.qty)
    return expanded, missing


def resolve_seat_deck(
    deck_id, decks: DeckDatabase, loader: LazyCardLoader
) -> tuple[list, list, list[str]]:
    """One seat's saved deck → (library, commanders, blocking errors).

    The shared resolution both `api/multiplayer.py` (a table seat) and
    `api/solo.py` (the human, and each bot opponent) use: parse the saved
    sections, resolve the names, apply Commander legality, and refuse
    anything illegal or unresolvable — every real game applies the same gate
    goldfish's `start_goldfish` above does.
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

    library, missing_lib = expand_entries(parsed.main_deck, resolved.cards)
    commanders, missing_cmd = expand_entries(parsed.commanders, resolved.cards)
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
        game_format=request.game_format,
    )
    view = session.view()
    view["notFound"] = sorted(set(missing) | set(resolved.not_found))
    return view


@router.get("/formats")
def list_formats() -> dict[str, object]:
    """The RULE 8/9 formats a game can be started in (PLR-13).

    Backs the format picker on both the Goldfisch start screen and the
    Multiplayer Setup table options — one endpoint, since a format is the
    same choice either way (`models/game_format.py`'s `FORMATS`).
    """
    from mtg_analyzer.models.game_format import DEFAULT_FORMAT, FORMATS

    return {
        "formats": [fmt.to_dict() for fmt in FORMATS.values()],
        "default": DEFAULT_FORMAT,
    }


@router.get("/tokens")
def known_tokens() -> dict[str, object]:
    """Every token in the repo's curated catalogue (`data/tokens.json`).

    Unlike `POST /deck-tokens` (a specific deck's *producible* tokens), this
    is deck-independent — it backs the "known token type" dropdown in
    Settings' token-image upload form (connectionSettingsView.js), so a
    player picks an exact, already-known token name instead of retyping one
    by hand (Soldier, Treasure, Clue, …). Ad hoc tokens an effect synthesizes
    inline (a bare "1/1 white Soldier" with no catalogue entry) aren't listed
    here — the same form's "generic" option covers those instead.
    """
    from mtg_analyzer.services.token_database import default_token_database

    tokens = default_token_database().all_tokens()
    return {
        "tokens": [
            {
                "id": t.id,
                "name": t.name,
                "type_line": t.type_line,
                "image_small": t.image_uri_small or None,
            }
            for t in sorted(tokens, key=lambda t: t.name)
        ]
    }


@router.post("/deck-tokens")
def deck_tokens(
    request: DeckTokensRequest,
    decks: DeckDatabase = Depends(get_deck_database),
    loader: LazyCardLoader = Depends(get_lazy_card_loader),
) -> dict[str, object]:
    """The tokens a deck can produce, for up-front art preloading (loading screen).

    Resolves the deck the same way `start_goldfish` does, then enumerates every
    ``create_token`` effect its cards carry (`producible_tokens`). Best-effort:
    unresolvable cards simply contribute no tokens; legality is *not* required
    (this only preloads art, it does not start a game).
    """
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
    library, _ = expand_entries(parsed.main_deck, resolved.cards)
    commanders, _ = expand_entries(parsed.commanders, resolved.cards)

    tokens = producible_tokens(commanders + library)
    return {
        "tokens": [
            {
                "id": t.id,
                "name": t.name,
                "type_line": t.type_line,
                "power": t.power,
                "toughness": t.toughness,
                "oracle_text": t.oracle_text,
                "image_small": t.image_uri_small or None,
                "image_normal": t.image_uri_normal or None,
            }
            for t in tokens
        ]
    }


@router.post("/replay")
def start_replay(
    request: StartReplayRequest,
    sessions: GameSessionManager = Depends(get_game_session_manager),
    loader: LazyCardLoader = Depends(get_lazy_card_loader),
) -> dict[str, object]:
    """Start a Replay/Puzzle session: load a saved board or a blank one.

    Pass a full ``replay`` descriptor (as produced by the export endpoint)
    to load it, or omit it for a blank board with ``num_players`` (1 = solo
    puzzle, 2-4 = with opponents). The board is editable via ``edit_*`` actions.
    """
    descriptor = request.replay or blank_replay(request.num_players)
    session = sessions.create_replay(descriptor, loader)
    return session.view()


@router.post("/multiplayer", status_code=501)
def start_multiplayer(
    sessions: GameSessionManager = Depends(get_game_session_manager),
) -> dict[str, object]:
    """Legacy seat-less entry point — still a 501 (UC4).

    Multiplayer itself is implemented (`api/multiplayer.py`), but a game
    can't be started from nothing: it needs seats (players, decks, an
    agreed mulligan style), which only the lobby has. Kept so an old client
    calling this gets a clear "use the lobby" rather than a 404.
    """
    try:
        sessions.create_multiplayer([])
    except MultiplayerNotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    return {}  # unreachable


@router.get("/{session_id}")
def get_session(
    session_id: str, sessions: GameSessionManager = Depends(get_game_session_manager)
) -> dict[str, object]:
    return _session(sessions, session_id).view()


@router.get("/{session_id}/replay-export")
def export_replay(
    session_id: str, sessions: GameSessionManager = Depends(get_game_session_manager)
) -> dict[str, object]:
    """Serialize any session's board to a portable replay descriptor.

    Works for a goldfish game too, so a position reached while goldfishing can
    be downloaded and re-opened in Replay mode.
    """
    return serialize_replay(_session(sessions, session_id).engine.state)


@router.post("/{session_id}/ui-draft")
def save_ui_draft(
    session_id: str,
    request: SaveUiDraftRequest,
    sessions: GameSessionManager = Depends(get_game_session_manager),
) -> dict[str, object]:
    """PLR-6: store (or clear) the caller's in-progress UI selection.

    Deliberately a quiet, unicast write — unlike `/action`, this never
    broadcasts (multiplayer's push channel is driven from `api/
    multiplayer.py`'s own `_after_move`, not from here), so autosaving a
    draft as it's built can't spam a fresh view at the rest of the table.
    """
    try:
        _session(sessions, session_id).set_ui_draft(request.player_id, request.draft)
    except GameActionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


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
