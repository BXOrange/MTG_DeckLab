"""Deck persistence endpoints: save, list, fetch, delete a saved decklist.

Distinct from `decks.py`'s `POST /api/decks`, which only parses and
structurally validates decklist text without storing anything.

Reference: docs/concepts/04_SERVER_CLIENT_ARCHITECTURE.md (PART 4, REST
endpoints), docs/implementation-state/Done_Backend.md "Deck persistence".
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from mtg_analyzer.api.cards import coverage_for
from mtg_analyzer.api.dependencies import get_deck_database, get_lazy_card_loader
from mtg_analyzer.api.schemas import SaveDeckRequest
from mtg_analyzer.game.card_registry import registry_signature
from mtg_analyzer.models.decks.deck import Deck
from mtg_analyzer.parser.deckliste_parser import parse_deck_sections
from mtg_analyzer.parser.oracle import PARSER_VERSION


def _coverage_cache_key() -> str:
    """The version stamp `Deck.unmodeled_coverage` is cached under.

    Folds the hand-`AUTHORED` catalogue's own state (`registry_signature`)
    into `PARSER_VERSION` so registering a card — which never bumps
    `PARSER_VERSION` — still invalidates every deck's stale "N cards not
    modeled" count on the next read, rather than freezing it until the
    decklist text changes.
    """
    return f"{PARSER_VERSION}+cat{registry_signature()}"
from mtg_analyzer.services.archetype_database import default_archetype_database
from mtg_analyzer.services.deck_database import DeckDatabase
from mtg_analyzer.services.deck_validation import apply_legality, compute_deck_identity
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
    is_cube = request.is_cube if request.is_cube is not None else (existing.is_cube if existing else False)
    # `validation_result` depends on `is_cube` too (a cube skips the RULE
    # checks entirely — `deck_validation.py`'s `apply_legality`), so a
    # cube-flag flip is exactly as invalidating for it as decklist text
    # changing, even though it doesn't touch `color_identity`/`commanders`/
    # `unmodeled_coverage` (none of those read `is_cube`).
    validation_stale = text_changed or (existing is not None and existing.is_cube != is_cube)
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
        is_cube=is_cube,
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
        # Same reset-only-when-stale treatment as color_identity/commanders
        # above — see `Deck`'s own docstring for why these two exist.
        validation_result=None if validation_stale else (existing.validation_result if existing else None),
        unmodeled_coverage=None if text_changed else (existing.unmodeled_coverage if existing else None),
        unmodeled_coverage_version=(
            None if text_changed else (existing.unmodeled_coverage_version if existing else None)
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
    goldfish deck picker, which only lets *legal* decks start a game. Every
    screen that lists saved decks fires this (and `/coverage` below) for
    *every* deck in parallel, so the result is cached on the deck itself
    (`Deck.validation_result`) once computed — `save_deck` resets it to
    `None` only when the decklist text or `is_cube` actually changed, so an
    unchanged deck is served straight from the database with no parsing, no
    card resolution, and no Scryfall exposure at all on a repeat view.
    """
    deck = database.get_deck(deck_id)
    if deck is None:
        raise HTTPException(status_code=404, detail=f'No saved deck with id "{deck_id}"')
    if deck.validation_result is not None:
        return deck.validation_result
    parsed = parse_deck_sections(deck.commander_text, deck.mainboard_text, deck.sideboard_text, deck.is_cube)
    resolved = loader.load_cards([e.name for e in parsed.commanders] + [e.name for e in parsed.all_cards])
    parsed = apply_legality(parsed, resolved, deck.is_cube)
    result = parsed.validation.to_dict()
    # Only persist the cache once every card actually resolved (`resolved.
    # not_found` empty) — a card that didn't (network hiccup, a still-cold
    # cache right after a schema wipe, …) means the real ban-list/color-
    # identity checks were skipped entirely (`apply_legality`'s own
    # incomplete-resolution fallback, which only adds a *warning* instead),
    # so this result could be wrong — caching it would freeze that wrong
    # answer until the decklist text next changes instead of self-healing
    # once resolution succeeds on a later view. Deliberately keyed off
    # `resolved.not_found` directly rather than `parsed.validation.warnings`
    # — that list also carries purely structural warnings (e.g. "no
    # commander detected", `deckliste_parser.py`'s own
    # `_validate_commander_deck`) that have nothing to do with resolution
    # and would otherwise block caching a perfectly good, fully-resolved
    # answer forever.
    if not resolved.not_found:
        deck.validation_result = result
        database.save_deck(deck)
    return result


@router.get("/{deck_id}/coverage")
def get_deck_coverage(
    deck_id: str,
    database: DeckDatabase = Depends(get_deck_database),
    loader: LazyCardLoader = Depends(get_lazy_card_loader),
) -> dict[str, object]:
    """How many of this deck's cards the rules engine doesn't model yet.

    A goldfishing readiness note, not a legality gate — an UNMODELED card is
    still a perfectly legal include, it just won't behave server-side yet.
    Counted over `parsed.all_cards` (commanders + mainboard, quantity-
    weighted) for both a normal deck and a `is_cube` pool alike; a card that
    failed to resolve is left out rather than counted as unmodeled, same as
    `_coverage_for`'s callers elsewhere. Cached the same way `/validation`
    above is (`Deck.unmodeled_coverage`) — see that docstring; the deck
    picker in every play-mode setup screen calls this once per saved deck in
    parallel (`gameSetup.js`'s `loadUnmodeledDeckIds`), so an unchanged deck
    must be a pure DB read here too.
    """
    deck = database.get_deck(deck_id)
    if deck is None:
        raise HTTPException(status_code=404, detail=f'No saved deck with id "{deck_id}"')
    if (
        deck.unmodeled_coverage is not None
        and deck.unmodeled_coverage_version == _coverage_cache_key()
    ):
        return deck.unmodeled_coverage
    parsed = parse_deck_sections(deck.commander_text, deck.mainboard_text, deck.sideboard_text, deck.is_cube)
    resolved = loader.load_cards([e.name for e in parsed.all_cards])
    unmodeled_count = 0
    unmodeled_card_names: list[str] = []
    for entry in parsed.all_cards:
        card = resolved.cards.get(entry.name)
        if card is None:
            continue
        if not coverage_for(card)["modeled"]:
            unmodeled_count += entry.qty
            unmodeled_card_names.append(entry.name)
    result = {
        "unmodeledCount": unmodeled_count,
        "unmodeledCardNames": sorted(unmodeled_card_names),
    }
    # Same "don't cache an incomplete answer" guard as `/validation` above —
    # a card that failed to resolve is silently excluded from the count
    # rather than counted as unmodeled, so caching here would freeze an
    # undercount until the decklist text next changes instead of
    # self-healing once resolution succeeds on a later view.
    if not resolved.not_found:
        deck.unmodeled_coverage = result
        deck.unmodeled_coverage_version = _coverage_cache_key()
        database.save_deck(deck)
    return result


@router.delete("/{deck_id}")
def delete_deck(deck_id: str, database: DeckDatabase = Depends(get_deck_database)) -> dict[str, object]:
    deleted = database.delete_deck(deck_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f'No saved deck with id "{deck_id}"')
    return {"deleted": True}
