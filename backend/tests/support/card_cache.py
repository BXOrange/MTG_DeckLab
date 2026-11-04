"""Named-card reads on one session-owned connection to the isolated test cache.

Only the connection is shared: get_card deserializes a fresh Card on every
lookup. Tests that write to a database must use their own CardDatabase.
"""

from functools import lru_cache

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH


@lru_cache(maxsize=1)
def _database() -> CardDatabase:
    return CardDatabase(DEFAULT_DB_PATH)


def get_cached_card(name: str) -> Card | None:
    return _database().get_card(name)


def close_card_cache() -> None:
    if _database.cache_info().currsize:
        _database().close()
        _database.cache_clear()
