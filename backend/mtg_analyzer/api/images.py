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


_VALID_FACES = ("front", "back")


@router.get("/{card_id}/image")
def get_card_image(
    card_id: str,
    size: str = Query("normal"),
    face: str = Query("front"),
    database: CardDatabase = Depends(get_card_database),
    images: ImageCache = Depends(get_image_cache),
) -> FileResponse:
    if size not in _VALID_SIZES:
        raise HTTPException(status_code=400, detail=f"size must be one of {_VALID_SIZES}")
    if face not in _VALID_FACES:
        raise HTTPException(status_code=400, detail=f"face must be one of {_VALID_FACES}")

    card = database.get_card_by_id(card_id)
    if card is None:
        raise HTTPException(status_code=404, detail=f'No cached card with id "{card_id}"')

    # Double-faced cards (transform, modal DFC) share one Scryfall id
    # across both faces; `face=back` serves the second face's own image.
    attr = f"back_image_uri_{size}" if face == "back" else f"image_uri_{size}"
    image_url = getattr(card, attr)
    if not image_url:
        raise HTTPException(
            status_code=404,
            detail=f'No "{size}" {face} image available for "{card.name}"',
        )

    path = images.get_or_fetch(card.id, size, image_url, face)
    return FileResponse(path)
