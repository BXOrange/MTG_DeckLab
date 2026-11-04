"""FastAPI application factory and instance for the DeckLab backend.

Reference: docs/concepts/04_SERVER_CLIENT_ARCHITECTURE.md (PART 7, Phase 1).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator

import anyio.to_thread
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from mtg_analyzer import config

from mtg_analyzer.api.admin import router as admin_router
from mtg_analyzer.api.archetypes import router as archetypes_router
from mtg_analyzer.api.cards import router as cards_router
from mtg_analyzer.api.combos import router as combos_router
from mtg_analyzer.api.decks import router as decks_router
from mtg_analyzer.api.dynamic_analysis import router as dynamic_analysis_router
from mtg_analyzer.api.frontend_proxy import router as frontend_proxy_router
from mtg_analyzer.api.game import router as game_router
from mtg_analyzer.api.images import router as images_router
from mtg_analyzer.api.import_external import router as import_external_router
from mtg_analyzer.api.security_events import SecurityEventMiddleware
from mtg_analyzer.api.mcp_seat import router as mcp_seat_router
from mtg_analyzer.api.mcp_settings import router as mcp_settings_router
from mtg_analyzer.api.multiplayer import router as multiplayer_router
from mtg_analyzer.api.dependencies import get_account_store, get_game_session_manager, get_lobby
from mtg_analyzer.api.multiplayer_ws import router as multiplayer_ws_router
from mtg_analyzer.api.multiplayer_ws import sweeper
from mtg_analyzer.api.player_assets import router as player_assets_router
from mtg_analyzer.api.saved_decks import router as saved_decks_router
from mtg_analyzer.api.solo import router as solo_router
from mtg_analyzer.api.stats import router as stats_router

from mtg_analyzer.api.request_guard import LOCAL_DEV_ORIGIN_REGEX as _LOCAL_DEV_ORIGIN_REGEX
from mtg_analyzer.api.request_guard import RequestGuardMiddleware
from mtg_analyzer.api.auth import router as auth_router
from mtg_analyzer.security_headers import SecurityHeadersMiddleware

logger = logging.getLogger(__name__)

#: uvicorn accepts a `trace` level that Python's `logging` has no name for
#: — treat it as `DEBUG` for the app's own loggers.
_LOG_LEVEL_ALIASES = {"TRACE": "DEBUG"}


def _configure_logging() -> None:
    """Set the level of the app's own `mtg_analyzer.*` loggers from
    `config.LOG_LEVEL` (default WARNING).

    Nothing in this project configured logging before, so `mtg_analyzer.*`
    records fell through to `logging.lastResort` — visible only at WARNING+
    and never at the level the operator asked for. This gives the
    `mtg_analyzer` parent logger an explicit level (so `--log info` really
    surfaces INFO) and, via `basicConfig`, a root stderr handler when one
    isn't already installed (tests, `python -m …`); under uvicorn the root
    stays handler-less and `basicConfig` is a no-op, uvicorn's own handler
    doing the emitting. The root level itself is left at WARNING so raising
    the app to DEBUG doesn't also unmute every third-party library.
    """
    name = _LOG_LEVEL_ALIASES.get(config.LOG_LEVEL, config.LOG_LEVEL)
    level = logging.getLevelNamesMapping().get(name, logging.WARNING)
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("mtg_analyzer").setLevel(level)


def _apply_server_thread_workers() -> None:
    """Resize the AnyIO worker-thread pool to `config.SERVER_THREAD_WORKERS`.

    Every gameplay endpoint is a synchronous `def`, so Starlette hands each
    call to this pool; its size is therefore the ceiling on how many games
    can be mid-step at the same time in this single process. AnyIO's own
    default is 40. Runs once at startup, from inside the event loop (the
    limiter is loop-bound). A bad value is logged and left alone rather
    than crashing the server on boot.
    """
    try:
        limiter = anyio.to_thread.current_default_thread_limiter()
        previous = limiter.total_tokens
        limiter.total_tokens = config.SERVER_THREAD_WORKERS
        if config.SERVER_THREAD_WORKERS != previous:
            logger.info(
                "server worker-thread pool set to %d (was %d)",
                config.SERVER_THREAD_WORKERS,
                previous,
            )
    except Exception:  # pragma: no cover - defensive, never block startup
        logger.warning(
            "could not resize the worker-thread pool to %r; using the default",
            config.SERVER_THREAD_WORKERS,
            exc_info=True,
        )


def _require_account_store() -> None:
    """PLR-9e: open the encrypted account database before serving anything.

    A missing or wrong key, or a legacy plaintext file, stops the start with the instructions in the
    error. It is never swallowed and never answered with a plaintext or empty database."""
    from mtg_analyzer.services.account_crypto import AccountDbError

    try:
        get_account_store()
    except AccountDbError as exc:
        logger.critical("ACCOUNT DATABASE UNAVAILABLE, refusing to start: %s", exc)
        raise


def _seed_initial_admin() -> None:
    """PLR-9d: on a fresh install open the initial setup (plan section 6), and warn while it is open.

    Not in `--online` (there the OS-operator command `create-admin` makes the first admin, who enrols MFA)."""
    from mtg_analyzer.api.auth import get_password_hasher
    from mtg_analyzer.services.account_store import INITIAL_ADMIN_NAME, INITIAL_ADMIN_PASSWORD

    if config.RUN_MODE == "online":
        return
    try:
        store = get_account_store()
        if not store.setup_open():
            store.seed_initial_admin(get_password_hasher().hash(INITIAL_ADMIN_PASSWORD))
        if store.setup_open():
            logger.warning(
                "ADMIN SETUP OPEN: the administrator '%s' still has the initial password. Open "
                "http://127.0.0.1:<port>/admin on this machine and set a new password "
                "(%d characters minimum) before serving players.",
                INITIAL_ADMIN_NAME, config.ADMIN_PASSWORD_MIN_LENGTH,
            )
    except Exception:  # pragma: no cover - never block startup
        logger.exception("could not prepare the initial admin setup")


def sweep_account_deletions() -> list[str]:
    """Delete the accounts whose deletion grace period elapsed (plan section 6, *Account deletion lifecycle*)."""
    from mtg_analyzer.api.dependencies import get_deck_database, get_player_asset_store
    from mtg_analyzer.services import admin_service

    store = get_account_store()
    deleted = admin_service.finalize_due_deletions(
        store, get_deck_database(), get_player_asset_store(), get_game_session_manager()
    )
    purged = store.purge_expired()  # PLR-9e: retention of dead sessions, credentials, audit entries
    if any(purged.values()):
        logger.info("retention sweep removed: %s", purged)
    return deleted


async def _deletion_sweeper() -> None:
    """Startup pass, then hourly: the multiplayer watchdog ticks every second and is table-scoped,
    so a slow account housekeeping job gets its own cheap loop instead of riding on it."""
    while True:
        try:
            deleted = await asyncio.to_thread(sweep_account_deletions)
            if deleted:
                logger.info("deleted %d account(s) after their deletion grace period", len(deleted))
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - a janitor that dies is worse
            logger.exception("account deletion sweep failed")
        await asyncio.sleep(config.ACCOUNT_DELETION_SWEEP_SECONDS)


@contextlib.asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Size the request thread pool, then run the multiplayer watchdog for
    as long as the server is up.

    The watchdog disconnects a player who is holding a table up (`config.
    MULTIPLAYER_IDLE_TIMEOUT_SECONDS`), gives up seats whose grace period
    lapsed, closes the sockets of logged-out/expired/disabled accounts and of
    dead tabs (PLR-9c), and passes priority for anyone currently absent so the players who *are*
    there can keep playing — see `api/multiplayer_ws.sweep_once`. Nothing
    else in the app needs a background task, so this is the whole lifespan.
    """
    _apply_server_thread_workers()
    _require_account_store()
    _seed_initial_admin()
    admin_listener = None
    if config.ADMIN_PORT:  # PLR-19: loopback-only admin socket of this same process
        from mtg_analyzer.api.admin_listener import AdminListener
        admin_listener = AdminListener(app, config.ADMIN_PORT, log_level=config.LOG_LEVEL.lower())
        await admin_listener.start()
    task = asyncio.create_task(
        sweeper(get_lobby(), get_game_session_manager(), get_account_store())
    )
    deletion_task = asyncio.create_task(_deletion_sweeper())
    try:
        yield
    finally:
        for running in (task, deletion_task):
            running.cancel()
        for running in (task, deletion_task):
            with contextlib.suppress(asyncio.CancelledError):
                await running
        if admin_listener is not None:
            await admin_listener.stop()


def create_app() -> FastAPI:
    _configure_logging()
    app = FastAPI(title="DeckLab API", lifespan=_lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=_LOCAL_DEV_ORIGIN_REGEX,
        # Session cookie + CSRF header for the --frontend-only two-origin case; the regex above is
        # loopback only, so credentials are never allowed for a foreign origin (plan §3).
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # Added after CORS so it is outermost: Host/Origin are vetted first (BUG-40/41/42).
    app.add_middleware(RequestGuardMiddleware)
    app.add_middleware(SecurityEventMiddleware)
    # Outermost of all, so even the guard's own 400/403 refusals carry the headers (BUG-44).
    app.add_middleware(SecurityHeadersMiddleware)
    from mtg_analyzer.api.console_status import router as console_status_router
    app.include_router(console_status_router)
    app.include_router(auth_router)
    app.include_router(admin_router)
    app.include_router(decks_router)
    app.include_router(saved_decks_router)
    app.include_router(archetypes_router)
    app.include_router(cards_router)
    app.include_router(combos_router)
    app.include_router(images_router)
    from mtg_analyzer.api.bug_reports import router as bug_reports_router
    app.include_router(bug_reports_router)
    app.include_router(game_router)
    app.include_router(dynamic_analysis_router)
    app.include_router(player_assets_router)
    app.include_router(import_external_router)
    app.include_router(multiplayer_router)
    app.include_router(mcp_seat_router)
    app.include_router(mcp_settings_router)
    app.include_router(multiplayer_ws_router)
    app.include_router(solo_router)
    app.include_router(stats_router)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    # Must be included last: its catch-all `/{path:path}` route would
    # otherwise shadow every route above it (see frontend_proxy.py).
    app.include_router(frontend_proxy_router)

    return app


app = create_app()
