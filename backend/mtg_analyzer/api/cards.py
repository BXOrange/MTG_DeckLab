"""Card lookup endpoints: single/batch resolution and listing the cache.

Reference: backend/ToDo_Backend.md "HTTP API foundation"
(`GET /api/cards/search`), docs/08_CARD_CACHE_EXPORT_IMPORT.md.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from mtg_analyzer.api.dependencies import get_card_database, get_lazy_card_loader
from mtg_analyzer.api.schemas import CardResolveRequest
from mtg_analyzer.services.card_database import CardDatabase
from mtg_analyzer.services.lazy_card_loader import LazyCardLoader

router = APIRouter(prefix="/api/cards", tags=["cards"])


@router.get("")
def list_cards(database: CardDatabase = Depends(get_card_database)) -> list[dict[str, object]]:
    """Every card currently in the local cache — for a "browse the cache" view."""
    return [card.to_dict() for card in database.list_cards()]


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
