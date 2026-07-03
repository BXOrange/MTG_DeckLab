"""Process-wide singletons for the card cache, shared across API routers.

`cards.py` (name resolution) and `images.py` (image bytes) both need a
`CardDatabase`; centralizing the singleton here means they share one
SQLite connection instead of each opening their own. Each getter is
overridden independently in tests via `app.dependency_overrides`.
"""

from __future__ import annotations

from functools import lru_cache

from mtg_analyzer.services.card_database import DEFAULT_DB_PATH, CardDatabase
from mtg_analyzer.services.image_cache import ImageCache
from mtg_analyzer.services.lazy_card_loader import LazyCardLoader
from mtg_analyzer.services.scryfall_client import ScryfallIntegration


@lru_cache(maxsize=1)
def _database() -> CardDatabase:
    return CardDatabase(DEFAULT_DB_PATH)


@lru_cache(maxsize=1)
def _lazy_card_loader() -> LazyCardLoader:
    return LazyCardLoader(_database(), ScryfallIntegration())


@lru_cache(maxsize=1)
def _image_cache() -> ImageCache:
    return ImageCache()


def get_card_database() -> CardDatabase:
    return _database()


def get_lazy_card_loader() -> LazyCardLoader:
    return _lazy_card_loader()


def get_image_cache() -> ImageCache:
    return _image_cache()
