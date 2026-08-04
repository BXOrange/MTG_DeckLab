"""FastAPI application factory and instance for the MTG Deck Analyzer backend.

Reference: docs/concepts/04_SERVER_CLIENT_ARCHITECTURE.md (PART 7, Phase 1).
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from mtg_analyzer.api.cards import router as cards_router
from mtg_analyzer.api.decks import router as decks_router
from mtg_analyzer.api.dynamic_analysis import router as dynamic_analysis_router
from mtg_analyzer.api.game import router as game_router
from mtg_analyzer.api.game_ws import router as game_ws_router
from mtg_analyzer.api.images import router as images_router
from mtg_analyzer.api.import_external import router as import_external_router
from mtg_analyzer.api.multiplayer import router as multiplayer_router
from mtg_analyzer.api.dependencies import get_game_session_manager, get_lobby
from mtg_analyzer.api.multiplayer_ws import router as multiplayer_ws_router
from mtg_analyzer.api.multiplayer_ws import sweeper
from mtg_analyzer.api.player_assets import router as player_assets_router
from mtg_analyzer.api.saved_decks import router as saved_decks_router

#: The frontend is a plain static server (setup/start.py, default port
#: 8765, overridable via --port) with no backend origin baked in, so any
#: local port is allowed rather than hardcoding one.
_LOCAL_DEV_ORIGIN_REGEX = r"http://(localhost|127\.0\.0\.1):\d+"


@contextlib.asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Run the multiplayer watchdog for as long as the server is up.

    It disconnects a player who is holding a table up (`config.
    MULTIPLAYER_IDLE_TIMEOUT_SECONDS`), gives up seats whose grace period
    lapsed, and passes priority for anyone currently absent so the players
    who *are* there can keep playing — see `api/multiplayer_ws.sweep_once`.
    Nothing else in the app needs a background task, so this is the whole
    lifespan.
    """
    task = asyncio.create_task(sweeper(get_lobby(), get_game_session_manager()))
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


def create_app() -> FastAPI:
    app = FastAPI(title="MTG Deck Analyzer API", lifespan=_lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=_LOCAL_DEV_ORIGIN_REGEX,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(decks_router)
    app.include_router(saved_decks_router)
    app.include_router(cards_router)
    app.include_router(images_router)
    app.include_router(game_router)
    app.include_router(game_ws_router)
    app.include_router(dynamic_analysis_router)
    app.include_router(player_assets_router)
    app.include_router(import_external_router)
    app.include_router(multiplayer_router)
    app.include_router(multiplayer_ws_router)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
