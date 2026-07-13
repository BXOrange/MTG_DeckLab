"""Central configuration: on-disk paths and small runtime constants.

Reference: backend/ToDo_Backend.md "Configuration".

Before this module existed, `CACHE_ROOT`/`DEFAULT_DB_PATH`
(`card_database.py`), `DATA_ROOT`/`DEFAULT_DECKS_DB_PATH`
(`deck_database.py`), `DEFAULT_PLAYER_ASSETS_DB_PATH`
(`player_assets.py`) and the Scryfall/`ImageCache` User-Agent constants
were each a hard-coded module constant with no override hook — a one-off
script or test run pointed at the same repo-relative cache/data
directories as any dev server that happened to be running, and (now that
`schema_version.py` can wipe a stale cache on open) could stomp its
database out from under it. Every on-disk path and related constant now
lives here instead, overridable via environment variable; modules that
need one import it from here rather than computing their own.

Env vars (all optional; defaults reproduce the pre-config-module paths):
  MTG_CACHE_DIR   — root of the disposable Scryfall cache (DB + images)
  MTG_DATA_DIR    — root of persistent user data (saved decks, player assets)
  MTG_USER_AGENT  — User-Agent sent to Scryfall (API + image CDN)
  MTG_SCRYFALL_MIN_REQUEST_INTERVAL — seconds between Scryfall API requests
"""

from __future__ import annotations

import os
from pathlib import Path

#: backend/ directory (this file lives at backend/mtg_analyzer/config.py) —
#: cache/ and data/ have always lived here, not at the outer repo root.
_BACKEND_ROOT = Path(__file__).resolve().parent.parent


def _env_path(name: str, default: Path) -> Path:
    override = os.environ.get(name)
    return Path(override).expanduser().resolve() if override else default


#: Root of the on-disk, lazily-populated card cache (Scryfall data,
#: entirely disposable — deleting it just means the next lookup re-fetches
#: from Scryfall). Gitignored; see docs/Reference/08_CARD_CACHE_EXPORT_IMPORT.md.
CACHE_DIR = _env_path("MTG_CACHE_DIR", _BACKEND_ROOT / "cache")

#: Root of on-disk, persistent application data (saved decks, player-
#: uploaded assets) — real user data with no upstream source to re-fetch,
#: unlike CACHE_DIR. Gitignored but NOT safe to delete.
DATA_DIR = _env_path("MTG_DATA_DIR", _BACKEND_ROOT / "data")

#: Default on-disk location for the lazily-populated card database.
DB_PATH = CACHE_DIR / "db" / "cards.db"

#: Default on-disk location for cached card images, keyed by Scryfall id
#: (see image_cache.py for the id-as-join-key layout).
IMAGE_CACHE_DIR = CACHE_DIR / "images"

#: Default on-disk location for saved decks.
DECKS_DB_PATH = DATA_DIR / "decks.db"

#: Default on-disk location for player-uploaded token art / sleeves.
PLAYER_ASSETS_DB_PATH = DATA_DIR / "player_assets.db"

#: User-Agent sent to Scryfall — both api.scryfall.com and the
#: cards.scryfall.io image CDN 400 requests with no User-Agent.
USER_AGENT = os.environ.get("MTG_USER_AGENT", "MTG-Deck-Analyzer/0.1")

#: Minimum delay between Scryfall API requests. Scryfall asks integrations
#: to stay under ~10 requests/second; this is the simplest way to honor
#: that without a background rate limiter.
SCRYFALL_MIN_REQUEST_INTERVAL_SECONDS = float(
    os.environ.get("MTG_SCRYFALL_MIN_REQUEST_INTERVAL", "0.1")
)
