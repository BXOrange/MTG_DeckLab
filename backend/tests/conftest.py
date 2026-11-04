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

Real local sockets are a separate opt-in tier: `real_socket` tests bind an OS
socket and fail in restricted sandboxes. Run them with `--socket-tests`.
In-process TestClient HTTP/WebSocket tests remain in the standard suite.
"""

import sys
from pathlib import Path

import pytest

#: Module-name prefixes that are always full-cache regressions.
_FULL_CACHE_MODULE_PREFIXES = ("test_cube_batch",)


def pytest_addoption(parser):
    parser.addoption(
        "--socket-tests", action="store_true", default=False,
        help="run integration tests that bind real local sockets (off in the standard suite)",
    )
    parser.addoption(
        "--full-cache",
        action="store_true",
        default=False,
        help="run tests that depend on the fully-populated local card cache "
        "(cube-batch regressions, Wyleth deck) — off by default.",
    )


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "real_socket: binds a real local socket; opt in with --socket-tests.",
    )
    config.addinivalue_line(
        "markers",
        "real_auth: do not auto-sign the API tests in as TEST_PLAYER_UUID (PLR-9b authorization tests).",
    )
    config.addinivalue_line(
        "markers",
        "remote_second_factor: test_api_admin_mfa uses a remote --online client (PLR-19: local admins skip the code).",
    )
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

    full_cache = config.getoption("--full-cache") or os.environ.get("MTG_FULL_CACHE_TESTS")
    skip = pytest.mark.skip(
        reason="full-cache test; opt in with --full-cache or MTG_FULL_CACHE_TESTS=1"
    )
    for item in items:
        if not full_cache and _is_full_cache(item):
            item.add_marker(skip)
        if not config.getoption("--socket-tests") and item.get_closest_marker("real_socket"):
            item.add_marker(pytest.mark.skip(reason="real local socket; opt in with --socket-tests"))


# ---------------------------------------------------------------------------
# Hand-built test cards: "costless + colour_identity" means "this card is that colour".
# ---------------------------------------------------------------------------
# RULE 202.2: real colour comes from the mana cost (or a colour indicator), and a costless card is colourless
# (BUG-13). Thousands of synthetic fixtures predate that and write ``Card(..., color_identity={"R"})`` with no
# cost to mean "a red card". For Cards constructed *directly by test code* (never by the engine / cache loader,
# so real cards are untouched) such a card gets a colour override equal to its identity. A test that exercises
# the real derivation opts out by listing its module in `_REAL_COLOR_MODULES`.

_TESTS_DIR = str(Path(__file__).resolve().parent)
_REAL_COLOR_MODULES = ("test_bug13_colors_vs_identity.py", "test_card_color_table_full_cache.py")


def _install_fixture_color_shim() -> None:
    from mtg_analyzer.models.cards.card import Card
    from mtg_analyzer.models.cards.card_colors import with_color_override

    original = Card.__init__

    def init(self, *args, **kwargs):
        original(self, *args, **kwargs)
        if not self.color_identity or (self.mana_cost_string or "").strip():
            return
        caller = sys._getframe(1).f_code.co_filename
        if caller.startswith(_TESTS_DIR) and not caller.endswith(_REAL_COLOR_MODULES):
            with_color_override(self, self.color_identity)

    Card.__init__ = init


_install_fixture_color_shim()


@pytest.fixture(autouse=True)
def _signed_in_test_player(request):
    """PLR-9b: deck/session routes need a verified player; sign the API tests in as one."""
    if request.node.get_closest_marker("real_auth") is not None:
        yield
        return
    import sys

    if "mtg_analyzer.api.app" not in sys.modules:  # not an API test: nothing to sign in
        yield
        return
    from fastapi import Request, WebSocket

    from mtg_analyzer.api.app import app
    from mtg_analyzer.api.auth import current_account, current_context, websocket_context
    from tests.support.auth import context_from_headers

    def http_identity(request: Request):
        return context_from_headers(request.headers)

    def socket_identity(websocket: WebSocket):
        return context_from_headers(websocket.headers)

    overrides = {current_account: http_identity, current_context: http_identity, websocket_context: socket_identity}
    app.dependency_overrides.update(overrides)
    yield
    for dep in overrides:
        app.dependency_overrides.pop(dep, None)


@pytest.fixture(scope="session")
def _account_isolation_root(tmp_path_factory):
    return tmp_path_factory.mktemp("account-isolation")


@pytest.fixture(autouse=True)
def _never_touch_the_real_account_key(_account_isolation_root, monkeypatch):
    """PLR-9e: no test reads or writes the operator's key (`~/.decklab/accounts.key`) or env key."""
    from mtg_analyzer import config
    from uuid import uuid4

    # mktemp scans all sibling names to allocate a number. Doing that twice
    # per test made a growing suite quadratic; these private names need no scan.
    root = _account_isolation_root / uuid4().hex
    keys, backups = root / "keys", root / "backups"
    keys.mkdir(parents=True)
    backups.mkdir()

    monkeypatch.delenv(config.ACCOUNTS_DB_KEY_ENV, raising=False)
    monkeypatch.setattr(config, "ACCOUNTS_DB_KEY_FILE", keys / "accounts.key")
    monkeypatch.setattr(config, "ACCOUNTS_BACKUP_DIR", backups)


@pytest.fixture(autouse=True)
def _never_touch_the_real_account_store():
    """PLR-9c: a test that forgets to override `get_account_store` gets a throwaway store, never `data/accounts.db`."""
    import sys

    if "mtg_analyzer.api.app" not in sys.modules:
        yield
        return
    from mtg_analyzer.api.app import app
    from mtg_analyzer.api.dependencies import get_account_store
    from tests.support.auth import ScratchAccountStore

    scratch = ScratchAccountStore()

    def override():
        return scratch

    app.dependency_overrides.setdefault(get_account_store, override)
    yield
    if app.dependency_overrides.get(get_account_store) is override:
        app.dependency_overrides.pop(get_account_store)
    scratch.close()


@pytest.fixture(autouse=True)
def _never_touch_the_real_deck_store(request):
    """A test that forgets to override `get_deck_database` gets a throwaway store, never `data/decks.db`."""
    import sys

    if "mtg_analyzer.api.app" not in sys.modules:
        yield
        return
    from mtg_analyzer.api.app import app
    from mtg_analyzer.api.dependencies import get_deck_database
    from mtg_analyzer.services.deck_database import DeckDatabase

    scratch = DeckDatabase(":memory:")

    def override():
        return scratch

    app.dependency_overrides.setdefault(get_deck_database, override)
    yield
    if app.dependency_overrides.get(get_deck_database) is override:
        app.dependency_overrides.pop(get_deck_database)
    scratch.close()


@pytest.fixture(autouse=True)
def _never_touch_the_real_asset_store():
    """PLR-16: a test that forgets to override `get_player_asset_store` gets a throwaway store, never `data/player_assets.db`."""
    import sys

    if "mtg_analyzer.api.app" not in sys.modules:
        yield
        return
    from mtg_analyzer.api.app import app
    from mtg_analyzer.api.dependencies import get_player_asset_store
    from mtg_analyzer.services.player_assets import PlayerAssetStore

    scratch = PlayerAssetStore(":memory:")

    def override():
        return scratch

    app.dependency_overrides.setdefault(get_player_asset_store, override)
    yield
    if app.dependency_overrides.get(get_player_asset_store) is override:
        app.dependency_overrides.pop(get_player_asset_store)
    scratch.close()
