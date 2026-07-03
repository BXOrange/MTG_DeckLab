"""On-disk cache of card images, downloaded lazily from Scryfall on first use.

Reference: docs/06_CARD_GRAPHICS_AND_LAZY_LOADING.md (PART 2/3),
docs/08_CARD_CACHE_EXPORT_IMPORT.md.

The link between a card and its cached images is implicit rather than a
stored path: both `CardDatabase` and this cache are keyed by the same
Scryfall `id` (`Card.id`). Given a card with id "abc123", its images
live at `cache/images/abc123/<size>.<ext>` — nothing in the database
row points at this directory, the id is the join key. This keeps
`CardDatabase` (a portable JSON blob per row) free of any
environment-specific filesystem paths, and lets the image cache be
deleted/rebuilt independently of the card data.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

import httpx2 as httpx

from mtg_analyzer.services.card_database import CACHE_ROOT

#: Default on-disk location for cached card images.
DEFAULT_IMAGE_CACHE_DIR = CACHE_ROOT / "images"

#: cards.scryfall.io (the image CDN, distinct from api.scryfall.com) 400s
#: requests with no User-Agent.
_USER_AGENT = "MTG-Deck-Analyzer/0.1"

#: File extension per Scryfall image size (see Card.image_uri_*).
_EXTENSION_BY_SIZE = {"small": "jpg", "normal": "jpg", "large": "jpg", "png": "png"}


class ImageCache:
    """Downloads and stores card images by (card id, size) on first request."""

    def __init__(
        self,
        cache_dir: Union[str, Path] = DEFAULT_IMAGE_CACHE_DIR,
        client: Optional[httpx.Client] = None,
    ) -> None:
        self._cache_dir = Path(cache_dir)
        self._client = client or httpx.Client(
            headers={"User-Agent": _USER_AGENT, "Accept": "image/*"}, timeout=10.0
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "ImageCache":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def path_for(self, card_id: str, size: str) -> Path:
        """Where this (card, size) image is/would be stored, whether or not it exists yet."""
        extension = _EXTENSION_BY_SIZE.get(size, "jpg")
        return self._cache_dir / card_id / f"{size}.{extension}"

    def get_or_fetch(self, card_id: str, size: str, image_url: str) -> Path:
        """Return the cached image path, downloading it first if not yet cached."""
        path = self.path_for(card_id, size)
        if path.exists():
            return path

        response = self._client.get(image_url)
        response.raise_for_status()

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(response.content)
        return path
