"""Deck persistence endpoints: save, list, fetch, delete a saved decklist.

Distinct from `decks.py`'s `POST /api/decks`, which only parses and
structurally validates decklist text without storing anything.

Reference: docs/concepts/04_SERVER_CLIENT_ARCHITECTURE.md (PART 4, REST
endpoints), docs/implementation-state/Done_Backend.md "Deck persistence".
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from mtg_analyzer.api.dependencies import get_deck_database, get_lazy_card_loader
from mtg_analyzer.api.schemas import SaveDeckRequest
from mtg_analyzer.models.deck import Deck
from mtg_analyzer.parser.deckliste_parser import parse_deck_sections
from mtg_analyzer.services.archetype_database import default_archetype_database
from mtg_analyzer.services.deck_database import DeckDatabase
from mtg_analyzer.services.deck_validation import compute_deck_identity, validate_deck_sections
from mtg_analyzer.services.lazy_card_loader import LazyCardLoader

router = APIRouter(prefix="/api/decks", tags=["decks"])

#: A deck may describe itself with at most this many archetypes — the
#: deck-edit UI offers exactly two `<select>`s, so this is a defensive
#: server-side cap rather than a load-bearing check (see CLAUDE.md "No
#: magic numbers").
MAX_DECK_ARCHETYPES = 2


def _clean_archetypes(archetypes: Optional[list[str]]) -> Optional[list[str]]:
    """Drop any id not in the archetype catalogue and cap at
    `MAX_DECK_ARCHETYPES`, preserving the caller's order."""
    if archetypes is None:
        return None
    db = default_archetype_database()
    known = [a for a in archetypes if db.get(a) is not None]
    return known[:MAX_DECK_ARCHETYPES]


def _ensure_identity(deck: Deck, database: DeckDatabase, loader: LazyCardLoader) -> Deck:
    """Fill in `deck.color_identity`/`deck.commanders` if not already cached.

    Resolving cards to compute these is the expensive part (a Scryfall/cache
    lookup per card), so once computed they're persisted back to the
    database and this becomes a no-op for that deck until its decklist text
    changes (`save_deck` resets both to `None` when it does).
    """
    if deck.color_identity is not None and deck.commanders is not None:
        return deck
    parsed = parse_deck_sections(deck.commander_text, deck.mainboard_text, deck.sideboard_text)
    resolved = loader.load_cards([e.name for e in parsed.commanders] + [e.name for e in parsed.all_cards])
    deck.color_identity, deck.commanders = compute_deck_identity(parsed, resolved)
    database.save_deck(deck)
    return deck


@router.post("/save")
def save_deck(
    request: SaveDeckRequest, database: DeckDatabase = Depends(get_deck_database)
) -> dict[str, object]:
    """Create a new saved deck, or update one if `id` matches an existing deck.

    A fresh UUID is generated when `id` is omitted; the response's `id`
    is what a client should send back on later saves to update this
    same deck instead of creating another one.
    """
    existing = database.get_deck(request.id) if request.id else None
    text_changed = existing is None or (
        existing.commander_text,
        existing.mainboard_text,
        existing.sideboard_text,
    ) != (request.commander_text, request.mainboard_text, request.sideboard_text)
    deck = Deck(
        id=existing.id if existing else request.id,
        name=request.name,
        commander_text=request.commander_text,
        mainboard_text=request.mainboard_text,
        sideboard_text=request.sideboard_text,
        created_at=existing.created_at if existing else None,
        analysis_id=existing.analysis_id if existing else None,
        # Settable via this same endpoint (the saved-decks list re-saves the
        # full deck with a new sleeveId), but preserved across unrelated
        # edits (e.g. re-saving decklist text) when the caller omits it.
        sleeve_id=request.sleeve_id if request.sleeve_id is not None else (existing.sleeve_id if existing else None),
        # Same preserve-on-omission treatment as sleeve_id above.
        author=request.author if request.author is not None else (existing.author if existing else None),
        # Reset when the decklist text actually changed (stale cache), keep
        # the cached values otherwise (e.g. a sleeve-only re-save).
        color_identity=None if text_changed else existing.color_identity,
        commanders=None if text_changed else existing.commanders,
        # Same preserve-on-omission treatment as sleeve_id/author above.
        is_cube=request.is_cube if request.is_cube is not None else (existing.is_cube if existing else False),
        # Same preserve-on-omission treatment, plus catalogue validation/cap
        # (see `_clean_archetypes`) — applied on every save, not just when
        # the caller sends a fresh value, so a stale/renamed catalogue id
        # from an old save can't linger forever.
        archetypes=_clean_archetypes(
            request.archetypes if request.archetypes is not None else (existing.archetypes if existing else None)
        ),
        favorite_cards=(
            request.favorite_cards if request.favorite_cards is not None else (existing.favorite_cards if existing else None)
        ),
    )
    database.save_deck(deck)
    return deck.to_dict()


@router.get("")
def list_decks(
    database: DeckDatabase = Depends(get_deck_database),
    loader: LazyCardLoader = Depends(get_lazy_card_loader),
) -> list[dict[str, object]]:
    """Every saved deck, newest first."""
    return [_ensure_identity(deck, database, loader).to_dict() for deck in database.list_decks()]


@router.get("/{deck_id}")
def get_deck(
    deck_id: str,
    database: DeckDatabase = Depends(get_deck_database),
    loader: LazyCardLoader = Depends(get_lazy_card_loader),
) -> dict[str, object]:
    deck = database.get_deck(deck_id)
    if deck is None:
        raise HTTPException(status_code=404, detail=f'No saved deck with id "{deck_id}"')
    return _ensure_identity(deck, database, loader).to_dict()


@router.get("/{deck_id}/validation")
def get_deck_validation(
    deck_id: str,
    database: DeckDatabase = Depends(get_deck_database),
    loader: LazyCardLoader = Depends(get_lazy_card_loader),
) -> dict[str, object]:
    """Commander legality of a saved deck (parses + resolves + validates).

    Backs the "illegal deck" badge in the saved-decks list and the
    goldfish deck picker, which only lets *legal* decks start a game.
    Resolving cards means this can hit Scryfall on first use for uncached
    cards; results are cached thereafter.
    """
    deck = database.get_deck(deck_id)
    if deck is None:
        raise HTTPException(status_code=404, detail=f'No saved deck with id "{deck_id}"')
    parsed = validate_deck_sections(
        deck.commander_text, deck.mainboard_text, deck.sideboard_text, loader, deck.is_cube
    )
    return parsed.validation.to_dict()


@router.delete("/{deck_id}")
def delete_deck(deck_id: str, database: DeckDatabase = Depends(get_deck_database)) -> dict[str, object]:
    deleted = database.delete_deck(deck_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f'No saved deck with id "{deck_id}"')
    return {"deleted": True}
