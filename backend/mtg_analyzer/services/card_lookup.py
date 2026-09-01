"""Process-wide read-only access to the card cache for the rules engine.

`game/` code occasionally needs to resolve a *real card by name* — a token
that's a copy of a **named** card (The Joiner of Cats' "a … copy of Lurrus
of the Dream-Den"). `api/dependencies.get_card_database()` is the FastAPI
request-scoped accessor and importing `api/` from `game/` is a layering
inversion; this module is the `game/`-safe equivalent, the same singleton
idiom as `services.token_database.default_token_database()`.

Deliberately a *separate* file from `services/card_database.py`: that module
is hashed into the cache's schema-version fingerprint
(`CardDatabase._SCHEMA_SOURCE_FILES`), so adding a function there would wipe
every cached row on the next open. Nothing here changes the stored format,
so it stays out of that fingerprint.
"""

from __future__ import annotations

from typing import Optional

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.models.card import Card
from mtg_analyzer.services.card_database import CardDatabase

_db: Optional[CardDatabase] = None


def default_card_database() -> CardDatabase:
    """The process-wide `CardDatabase` on the configured on-disk cache path.
    Built lazily on first use; read-only in this role (never written)."""
    global _db
    if _db is None:
        _db = CardDatabase(DB_PATH)
    return _db


def card_by_name(name: str) -> Optional[Card]:
    """Resolve a card by exact (case-insensitive) name from the cache, or
    ``None`` if it isn't cached (an offline/empty cache — callers treat that
    as "do as much as possible", RULE 608.2b)."""
    if not name:
        return None
    return default_card_database().get_card(name)
