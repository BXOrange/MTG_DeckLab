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

from pathlib import Path

import pytest

from tests.domains import DOMAINS, domain_map_for

#: Module-name prefixes that are always full-cache regressions.
_FULL_CACHE_MODULE_PREFIXES = ("test_cube_batch",)


def _share_test_card_cache_connection() -> None:
    """Open the test card cache once per process instead of once per `CardDatabase(DB_PATH)`.

    ~260 test files resolve real cards through `CardDatabase(DB_PATH)` in a
    helper that runs once per test (often several times). Every open runs the
    schema script, whose `INSERT OR IGNORE ... SELECT ... WHERE flavor_name != ''`
    scans the whole ~70 MB `cards` table: ~75 ms each, which measured as ~93% of
    a typical card test's runtime (the test logic itself is ~15 ms). Sharing one
    connection for that one path removes the cost without touching the
    production class (editing `card_database.py` would change the schema hash
    and wipe the production cache).

    Only `DB_PATH` is shared; `:memory:` and `tmp_path` databases (schema,
    reopen and close tests) keep their normal behaviour. `close()` is a no-op
    on the shared instance so one test cannot close it for the next. Opt out
    with MTG_TEST_NO_DB_SHARE=1.
    """
    import os

    if os.environ.get("MTG_TEST_NO_DB_SHARE"):
        return
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.services.card_database import CardDatabase

    shared_path = os.fspath(DB_PATH)
    original_init, original_close = CardDatabase.__init__, CardDatabase.close
    first: list[CardDatabase] = []

    def init(self, db_path=":memory:"):
        if os.fspath(db_path) != shared_path:
            original_init(self, db_path)
            return
        if not first:
            original_init(self, db_path)
            first.append(self)
            return
        self.__dict__.update(first[0].__dict__)  # same connection, lock and schema_reset

    def close(self):
        if first and self._connection is first[0]._connection:
            return
        original_close(self)

    CardDatabase.__init__ = init
    CardDatabase.close = close


_share_test_card_cache_connection()


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
    for domain in DOMAINS:
        config.addinivalue_line(
            "markers",
            f"domain_{domain}: test belongs to the {domain} domain (auto-assigned "
            "from tests/domains.py); run one domain with -m domain_" + domain,
        )


def _is_full_cache(item) -> bool:
    if item.get_closest_marker("full_cache") is not None:
        return True
    module = item.module.__name__.rsplit(".", 1)[-1]
    return module.startswith(_FULL_CACHE_MODULE_PREFIXES)


#: Bot/session/multiplayer tests drive whole games (the slowest take ~19 s alone
#: on an idle machine) so the global 20 s ceiling in pytest.ini turns them into
#: load-dependent flakes under `-n`. 60 s still catches a real hang.
SLOW_DOMAINS = frozenset({"session_bots", "bots", "multiplayer", "api"})
SLOW_DOMAIN_TIMEOUT_S = 60


def _tag_domains(items) -> None:
    """Add `domain_<x>` markers so `-m domain_card` selects by product area."""
    files = {Path(str(item.path)) for item in items}
    domains = domain_map_for(sorted(files))
    for item in items:
        key = Path(str(item.path)).resolve().relative_to(
            Path(__file__).resolve().parent.parent.parent).as_posix()
        item_domains = domains.get(key, ())
        for domain in item_domains:
            item.add_marker(getattr(pytest.mark, f"domain_{domain}"))
        if SLOW_DOMAINS.intersection(item_domains) and item.get_closest_marker("timeout") is None:
            item.add_marker(pytest.mark.timeout(SLOW_DOMAIN_TIMEOUT_S))


def pytest_collection_modifyitems(config, items):
    import os

    _tag_domains(items)

    if config.getoption("--full-cache") or os.environ.get("MTG_FULL_CACHE_TESTS"):
        return
    skip = pytest.mark.skip(
        reason="full-cache test; opt in with --full-cache or MTG_FULL_CACHE_TESTS=1"
    )
    for item in items:
        if _is_full_cache(item):
            item.add_marker(skip)
