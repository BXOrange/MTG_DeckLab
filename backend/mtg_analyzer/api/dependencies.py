"""Process-wide singletons for card/deck storage, shared across API routers.

`cards.py` (name resolution) and `images.py` (image bytes) both need a
`CardDatabase`; `saved_decks.py` needs a `DeckDatabase`. Centralizing
the singletons here means each is opened once and shared, instead of
every router opening its own connection. Each getter is overridden
independently in tests via `app.dependency_overrides`.
"""

from __future__ import annotations

from functools import lru_cache

import httpx2 as httpx

from mtg_analyzer.config import (
    ACCOUNTS_DB_PATH,
    DATA_DIR,
    DB_PATH,
    DECKS_DB_PATH,
    FRONTEND_ORIGIN,
    IMAGE_CACHE_DIR,
    PLAYER_ASSETS_DB_PATH,
    SCRYFALL_PRIMARY,
)
from mtg_analyzer.services import account_crypto
from mtg_analyzer.services.account_store import AccountStore
from mtg_analyzer.services.admin_jobs import AdminJobs
from mtg_analyzer.services.archidekt_client import ArchidektClient
from mtg_analyzer.services.card_database import CardDatabase
from mtg_analyzer.services.commander_spellbook_database import CommanderSpellbookDatabase
from mtg_analyzer.services.deck_database import DeckDatabase
from mtg_analyzer.services.dynamic_analysis import DynamicAnalysisJobs
from mtg_analyzer.services.game_session import GameSessionManager
from mtg_analyzer.services.image_cache import ImageCache
from mtg_analyzer.services.lazy_card_loader import LazyCardLoader
from mtg_analyzer.services.lobby import Lobby
from mtg_analyzer.services.player_assets import PlayerAssetStore, bind_account_cleanup
from mtg_analyzer.services.scryfall_client import ScryfallIntegration


@lru_cache(maxsize=1)
def _database() -> CardDatabase:
    return CardDatabase(DB_PATH)


@lru_cache(maxsize=1)
def _lazy_card_loader() -> LazyCardLoader:
    return LazyCardLoader(_database(), ScryfallIntegration(), scryfall_primary=SCRYFALL_PRIMARY)


@lru_cache(maxsize=1)
def _image_cache() -> ImageCache:
    return ImageCache(IMAGE_CACHE_DIR)


@lru_cache(maxsize=1)
def _deck_database() -> DeckDatabase:
    database = DeckDatabase(DECKS_DB_PATH)
    account_crypto.harden_data_dir(DATA_DIR)  # PLR-9e: owner-only data directory and files
    return database


@lru_cache(maxsize=1)
def _account_store() -> AccountStore:
    # PLR-9e: the key comes from outside the data directory; a missing or wrong key raises and the
    # app refuses to start (no plaintext fallback, no fresh database over an existing one).
    key = account_crypto.resolve_key(ACCOUNTS_DB_PATH, allow_create=True)
    store = AccountStore(ACCOUNTS_DB_PATH, key=key)
    account_crypto.harden_data_dir(DATA_DIR)
    # PLR-16: deleting an account removes the assets it owns.
    bind_account_cleanup(store, _player_asset_store())
    return store


@lru_cache(maxsize=1)
def _commander_spellbook_database() -> CommanderSpellbookDatabase:
    return CommanderSpellbookDatabase()


@lru_cache(maxsize=1)
def _game_session_manager() -> GameSessionManager:
    # In-memory, process-wide: game sessions vanish on restart (like the
    # WebSocket connection manager). Fine for local single-process play.
    manager = GameSessionManager()
    # BUG-43: a session a lobby table points at lives and dies with its table.
    manager.set_protected_provider(
        lambda: {g.session_id for g in _lobby().games() if g.session_id}
    )
    return manager


@lru_cache(maxsize=1)
def _lobby() -> Lobby:
    # In-memory, process-wide, like the session manager above: the lobby is
    # presence, and presence has no meaning across a restart.
    return Lobby()


@lru_cache(maxsize=1)
def _player_asset_store() -> PlayerAssetStore:
    store = PlayerAssetStore(PLAYER_ASSETS_DB_PATH)
    account_crypto.harden_data_dir(DATA_DIR)
    return store


@lru_cache(maxsize=1)
def _archidekt_client() -> ArchidektClient:
    return ArchidektClient()


@lru_cache(maxsize=1)
def _dynamic_analysis_jobs() -> DynamicAnalysisJobs:
    # In-memory, process-wide, like the session manager above (ANA-4):
    # a running/finished simulation job has no meaning across a restart.
    return DynamicAnalysisJobs()


@lru_cache(maxsize=1)
def _admin_jobs() -> AdminJobs:
    # In-memory, process-wide (PLR-9d): an update job has no meaning across a restart.
    return AdminJobs()


@lru_cache(maxsize=1)
def _frontend_proxy_client() -> httpx.Client:
    # Reused across requests (connection pooling) rather than opening a new
    # connection per proxied asset. base_url is FRONTEND_ORIGIN so route
    # handlers just pass the request path straight through.
    return httpx.Client(base_url=FRONTEND_ORIGIN, timeout=5.0)


def get_card_database() -> CardDatabase:
    return _database()


def get_account_store() -> AccountStore:
    return _account_store()


def get_lazy_card_loader() -> LazyCardLoader:
    return _lazy_card_loader()


def get_image_cache() -> ImageCache:
    return _image_cache()


def get_deck_database() -> DeckDatabase:
    return _deck_database()


def get_commander_spellbook_database() -> CommanderSpellbookDatabase:
    return _commander_spellbook_database()


def get_game_session_manager() -> GameSessionManager:
    return _game_session_manager()


def get_lobby() -> Lobby:
    return _lobby()


def get_player_asset_store() -> PlayerAssetStore:
    return _player_asset_store()


def get_archidekt_client() -> ArchidektClient:
    return _archidekt_client()


def get_dynamic_analysis_jobs() -> DynamicAnalysisJobs:
    return _dynamic_analysis_jobs()


def get_admin_jobs() -> AdminJobs:
    return _admin_jobs()


def get_frontend_proxy_client() -> httpx.Client:
    return _frontend_proxy_client()
