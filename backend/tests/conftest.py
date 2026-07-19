"""Pytest configuration for the backend test suite.

Full-card-cache tests are opt-in
--------------------------------
Some tests exercise the *real, fully-populated* local card cache
(`services/card_database.py`'s `DEFAULT_DB_PATH`) rather than inline `Card`
fixtures — the cEDH cube-batch regressions (`test_cube_batch_*`) and the Wyleth
Boros deck. They historically self-skipped whenever the cache was absent, so on
a fresh checkout they simply didn't run. Once the cache is bulk-loaded with the
full ~30k-card universe (`scripts/import_bulk.py`), that skip no longer fires
and they turn the ordinary `pytest` run into a heavyweight pass over the whole
card database.

Per the project owner's instruction — "make the full card coverage not a
regular part of testing" — these are now **opt-in**: skipped by default so the
regular suite stays fast and deterministic on synthetic fixtures, and run only
when explicitly requested:

    pytest --full-cache            # or:
    MTG_FULL_CACHE_TESTS=1 pytest

A test is treated as full-cache if it carries the `full_cache` marker OR lives
in a `test_cube_batch_*` module (the established naming convention, so new
cube batches are covered automatically with no per-file change).
"""

import pytest

#: Module-name prefixes that are always full-cache regressions.
_FULL_CACHE_MODULE_PREFIXES = ("test_cube_batch",)


def pytest_addoption(parser):
    parser.addoption(
        "--full-cache",
        action="store_true",
        default=False,
        help="run tests that depend on the fully-populated local card cache "
        "(cube-batch regressions, Wyleth deck) — off by default.",
    )


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "full_cache: test depends on a fully-populated local card cache; "
        "opt in with --full-cache or MTG_FULL_CACHE_TESTS=1.",
    )


def _is_full_cache(item) -> bool:
    if item.get_closest_marker("full_cache") is not None:
        return True
    module = item.module.__name__.rsplit(".", 1)[-1]
    return module.startswith(_FULL_CACHE_MODULE_PREFIXES)


def pytest_collection_modifyitems(config, items):
    import os

    if config.getoption("--full-cache") or os.environ.get("MTG_FULL_CACHE_TESTS"):
        return
    skip = pytest.mark.skip(
        reason="full-cache test; opt in with --full-cache or MTG_FULL_CACHE_TESTS=1"
    )
    for item in items:
        if _is_full_cache(item):
            item.add_marker(skip)
