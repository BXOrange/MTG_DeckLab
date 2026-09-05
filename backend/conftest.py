import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

# Isolate the test session's Scryfall card cache from the real, on-disk
# production one (backend/cache/db/cards.db, the same file a running dev
# server reads/writes). Dozens of tests (every "*_family.py"/"test_cube_
# batch_*.py"'s `_named`/`CardDatabase(DB_PATH)` helper) resolve real cards
# by name straight out of the *default* app cache path rather than an
# isolated fixture, because they need real card data an inline `Card(...)`
# fixture can't practically stand in for. Without this, running the test
# suite is indistinguishable from a second process sharing the dev server's
# cache — and `CardDatabase` wipes that cache outright on any `models/
# card.py`/schema-format change (`services/card_database.py`'s
# `_clear_on_schema_change`), so editing that file and then running pytest
# silently deleted the real, ~35k-card production cache from under a
# running server (the incident behind `Done_Backend.md`'s "Deck
# persistence" entry, 2026-09-05).
#
# `MTG_CACHE_DIR` is the project's existing "point elsewhere" knob
# (`mtg_analyzer/config.py`; `scripts/import_bulk.py`'s own docstring
# already recommends it for exactly this — "Point it at a scratch app cache
# with MTG_CACHE_DIR to avoid clobbering a running dev server"). Setting it
# here, before `mtg_analyzer.config` (and everything that imports it) is
# ever imported anywhere in the test process, redirects every `CardDatabase
# (DB_PATH)`/`CardDatabase(DEFAULT_DB_PATH)` instantiated during the whole
# session to this isolated copy instead — no changes needed to any
# individual test file. `setdefault` so an operator who explicitly exported
# their own `MTG_CACHE_DIR` before invoking pytest keeps that choice.
_TEST_CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache", "test")
os.environ.setdefault("MTG_CACHE_DIR", _TEST_CACHE_DIR)


def _ensure_test_cache_seeded() -> None:
    """Populate the isolated test cache with real card data if it's empty.

    A fresh copy (first run on this machine, or one just wiped by a
    `models/card.py` change earlier this same session) has zero rows, which
    would silently turn every "*_family.py"/cube-batch test that resolves a
    real card by name into a false failure (``None``, then an
    `AttributeError` deep inside `GameObject` — the exact failure mode that
    motivated this isolation in the first place). Reseeded from the
    persistent, durable `RawCardStore` (`DATA_DIR/scryfall_raw.db`) — a
    fast, purely local, offline pass (`scripts/import_bulk.py --reseed-
    only`'s own logic, reused directly here) that never touches Scryfall
    and never touches the *production* app cache either, since `RawCardStore`
    is read-only from this function's perspective (only ever `.iter_raw()`/
    `.count()`, never written to) and lives under `DATA_DIR`, not the
    `MTG_CACHE_DIR` this file just redirected.

    A completely fresh checkout with no raw store yet (nobody has ever run
    `scripts/import_bulk.py` at all) leaves the test cache empty and moves
    on without error — the same "self-skip when the cache is absent"
    behavior `tests/conftest.py`'s full-cache opt-in already documents for
    this exact scenario, not a new failure mode.
    """
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.services.card_database import CardDatabase
    from mtg_analyzer.services.raw_card_store import RawCardStore
    from scripts.import_bulk import _seed_cache_from_store

    db = CardDatabase(DB_PATH)
    try:
        if db.count() > 0:
            return
    finally:
        db.close()

    store = RawCardStore()
    try:
        if store.count() == 0:
            return  # nothing to seed from yet — fine, see docstring above
        print(f"\n[conftest] Seeding isolated test card cache at {DB_PATH} "
              f"from the raw store ({store.count()} cards, offline)…")
        saved, _skipped, _failed = _seed_cache_from_store(store, DB_PATH, None)
        print(f"[conftest] Test card cache ready: {saved} cards.")
    finally:
        store.close()


_ensure_test_cache_seeded()
