"""GET /api/cards/{card_id}/image: serve a card image, caching it to disk on first use.

The card must already be in the CardDatabase (i.e. resolved once via
GET /api/cards/search) since that's where its Scryfall image URLs come
from; this endpoint doesn't itself talk to Scryfall's card-data API,
only its image CDN.

Reference: docs/06_CARD_GRAPHICS_AND_LAZY_LOADING.md,
docs/08_CARD_CACHE_EXPORT_IMPORT.md.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from mtg_analyzer.api.dependencies import get_card_database, get_image_cache
from mtg_analyzer.services.card_database import CardDatabase
from mtg_analyzer.services.image_cache import ImageCache

router = APIRouter(prefix="/api/cards", tags=["cards"])

_VALID_SIZES = ("small", "normal", "large", "png")


@router.get("/{card_id}/image")
def get_card_image(
    card_id: str,
    size: str = Query("normal"),
    database: CardDatabase = Depends(get_card_database),
    images: ImageCache = Depends(get_image_cache),
) -> FileResponse:
    if size not in _VALID_SIZES:
        raise HTTPException(status_code=400, detail=f"size must be one of {_VALID_SIZES}")

    card = database.get_card_by_id(card_id)
    if card is None:
        raise HTTPException(status_code=404, detail=f'No cached card with id "{card_id}"')

    image_url = getattr(card, f"image_uri_{size}")
    if not image_url:
        raise HTTPException(status_code=404, detail=f'No "{size}" image available for "{card.name}"')

    path = images.get_or_fetch(card.id, size, image_url)
    return FileResponse(path)
