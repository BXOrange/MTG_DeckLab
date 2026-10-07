"""Card lookup endpoints: single/batch resolution and listing the cache.

Reference: docs/implementation-state/Done_Backend.md "HTTP API foundation"
(`GET /api/cards/search`), docs/Reference/08_CARD_CACHE_EXPORT_IMPORT.md.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from mtg_analyzer.api.dependencies import get_card_database, get_deck_database, get_lazy_card_loader
from mtg_analyzer.api.schemas import CardResolveRequest
from mtg_analyzer.game import card_registry
from mtg_analyzer.parser.deckliste_parser import parse_deck_sections
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.card_database import CardDatabase
from mtg_analyzer.services.deck_database import DeckDatabase
from mtg_analyzer.services.lazy_card_loader import LazyCardLoader

router = APIRouter(prefix="/api/cards", tags=["cards"])
logger = logging.getLogger(__name__)

_CARD_POOL_UPDATE_TIMEOUT_SECONDS = 15 * 60
_CARD_POOL_UPDATE_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "update_card_pool.py"


def coverage_for(card: Any) -> dict[str, object]:
    """A card's engine-coverage verdict (docs/09 "coverage is the roadmap").

    A hand-authored `card_registry` entry is trusted wholesale, same as
    `specs_for` treats it — `MODELED` with no unclaimed lines regardless of
    what the oracle parser alone would say. Otherwise this is exactly the
    verdict `specs_for` falls back to for binding, so "modeled" here means
    "the engine plays this card's abilities", not just "text parses".
    """
    if card_registry.is_authored_card(card):
        return {"modeled": True, "source": "catalogue", "unclaimed": []}
    result = parse_oracle(card)
    return {"modeled": result.modeled, "source": "oracle", "unclaimed": result.unclaimed}


def _cards_referenced_by_decks(database: CardDatabase, decks: DeckDatabase) -> list[Any]:
    """Cached cards referenced by at least one saved deck (any section).

    Only matches what's already cached — like `CardDatabase.list_cards`,
    this never triggers a Scryfall fetch for a deck's uncached cards; it's a
    "browse the cache" view, not a resolver (`GET /api/decks` already keeps
    a deck's cards resolved via `_ensure_identity`/`LazyCardLoader`).
    """
    names: set[str] = set()
    for deck in decks.list_decks():
        parsed = parse_deck_sections(
            deck.commander_text, deck.mainboard_text, deck.sideboard_text, deck.is_cube
        )
        names.update(entry.name for entry in (*parsed.all_cards, *parsed.sideboard))

    seen_ids: set[str] = set()
    cards = []
    for name in names:
        card = database.get_card(name)
        if card is not None and card.id not in seen_ids:
            seen_ids.add(card.id)
            cards.append(card)
    cards.sort(key=lambda c: c.name)
    return cards


@router.get("")
def list_cards(
    scope: str = Query("all", pattern="^(all|decks)$"),
    database: CardDatabase = Depends(get_card_database),
    decks: DeckDatabase = Depends(get_deck_database),
) -> list[dict[str, object]]:
    """Cards in the local cache — for a "browse the cache" view.

    `scope=all` (default) is every cached card, including the full bulk
    Oracle import (docs/09). `scope=decks` narrows that down to cards
    actually referenced by a saved deck, for a much smaller/more relevant
    list once the bulk cache is loaded.
    """
    source = _cards_referenced_by_decks(database, decks) if scope == "decks" else database.list_cards()
    cards = []
    for card in source:
        card_dict = card.to_dict()
        card_dict["coverage"] = coverage_for(card)
        cards.append(card_dict)
    return cards


@router.get("/coverage-by-set")
def coverage_by_set(
    database: CardDatabase = Depends(get_card_database),
) -> list[dict[str, object]]:
    """Parser/engine coverage aggregated by set, for the Engine-Status tab's
    "Abdeckung nach Set" table (`implementationStatusView.js`).

    Same per-card verdict `GET /api/cards` already computes (`coverage_for`,
    relying on `parse_oracle`'s own per-process memoization to keep repeat
    calls cheap) — just grouped by `Card.set_code` instead of listed per card.
    """
    totals: dict[str, dict[str, int]] = {}
    for card in database.list_cards():
        set_code = card.set_code or "?"
        bucket = totals.setdefault(set_code, {"total": 0, "covered": 0})
        bucket["total"] += 1
        if coverage_for(card)["modeled"]:
            bucket["covered"] += 1

    rows = [
        {
            "setCode": set_code,
            "total": stats["total"],
            "covered": stats["covered"],
            "fraction": (stats["covered"] / stats["total"]) if stats["total"] else 0.0,
        }
        for set_code, stats in totals.items()
    ]
    rows.sort(key=lambda row: row["setCode"])
    return rows


@router.get("/search")
def search_card(
    name: str = Query(..., min_length=1),
    loader: LazyCardLoader = Depends(get_lazy_card_loader),
) -> dict[str, object]:
    """Resolve a single card by exact name, fetching from Scryfall on first use."""
    result = loader.load_cards([name])
    card = result.cards.get(name)
    if card is None:
        raise HTTPException(status_code=404, detail=f'No card found for "{name}"')
    return card.to_dict()


@router.post("/resolve")
def resolve_cards(
    request: CardResolveRequest,
    loader: LazyCardLoader = Depends(get_lazy_card_loader),
) -> dict[str, object]:
    """Resolve many card names in one round trip (e.g. a whole decklist).

    Batches the underlying Scryfall lookups (LazyCardLoader ->
    ScryfallIntegration.fetch_multiple) rather than requiring one
    /search call per card.
    """
    result = loader.load_cards(request.names)
    return {
        "cards": {name: card.to_dict() for name, card in result.cards.items()},
        "notFound": result.not_found,
    }


@router.post("/update")
def update_card_pool(database: CardDatabase = Depends(get_card_database)) -> dict[str, object]:
    """Refresh the full Scryfall Oracle card pool using the existing importer."""
    try:
        result = subprocess.run(
            [sys.executable, str(_CARD_POOL_UPDATE_SCRIPT)],
            cwd=_CARD_POOL_UPDATE_SCRIPT.parent.parent,
            capture_output=True,
            check=False,
            text=True,
            timeout=_CARD_POOL_UPDATE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        logger.error("Full Scryfall card-pool update exceeded its time limit.")
        raise HTTPException(
            status_code=504,
            detail="The Scryfall card-pool update timed out. Check the server log and retry.",
        ) from exc

    if result.returncode != 0:
        logger.error(
            "Full Scryfall card-pool update failed (exit %s): %s",
            result.returncode,
            (result.stderr or result.stdout)[-4000:],
        )
        raise HTTPException(
            status_code=502,
            detail="The Scryfall card-pool update failed. Check the server log for details.",
        )

    logger.info("Full Scryfall card-pool update completed: %s", result.stdout[-1000:])
    return {"updated": True, "cachedCardCount": database.count()}
