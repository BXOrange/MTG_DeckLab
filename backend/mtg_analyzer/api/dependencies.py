"""Process-wide singletons for card/deck storage, shared across API routers.

`cards.py` (name resolution) and `images.py` (image bytes) both need a
`CardDatabase`; `saved_decks.py` needs a `DeckDatabase`. Centralizing
the singletons here means each is opened once and shared, instead of
every router opening its own connection. Each getter is overridden
independently in tests via `app.dependency_overrides`.
"""

from __future__ import annotations

from functools import lru_cache

from mtg_analyzer.services.card_database import DEFAULT_DB_PATH, CardDatabase
from mtg_analyzer.services.deck_database import DEFAULT_DECKS_DB_PATH, DeckDatabase
from mtg_analyzer.services.game_session import GameSessionManager
from mtg_analyzer.services.image_cache import ImageCache
from mtg_analyzer.services.lazy_card_loader import LazyCardLoader
from mtg_analyzer.services.player_assets import DEFAULT_PLAYER_ASSETS_DB_PATH, PlayerAssetStore
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


@lru_cache(maxsize=1)
def _deck_database() -> DeckDatabase:
    return DeckDatabase(DEFAULT_DECKS_DB_PATH)


@lru_cache(maxsize=1)
def _game_session_manager() -> GameSessionManager:
    # In-memory, process-wide: game sessions vanish on restart (like the
    # WebSocket connection manager). Fine for local single-process play.
    return GameSessionManager()


@lru_cache(maxsize=1)
def _player_asset_store() -> PlayerAssetStore:
    return PlayerAssetStore(DEFAULT_PLAYER_ASSETS_DB_PATH)


def get_card_database() -> CardDatabase:
    return _database()


def get_lazy_card_loader() -> LazyCardLoader:
    return _lazy_card_loader()


def get_image_cache() -> ImageCache:
    return _image_cache()


def get_deck_database() -> DeckDatabase:
    return _deck_database()


def get_game_session_manager() -> GameSessionManager:
    return _game_session_manager()


def get_player_asset_store() -> PlayerAssetStore:
    return _player_asset_store()
