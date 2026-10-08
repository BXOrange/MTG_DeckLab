"""Local Commander Spellbook combo database API."""

from __future__ import annotations

import logging

import httpx2 as httpx
from fastapi import APIRouter, Depends, HTTPException

from mtg_analyzer.api.dependencies import get_commander_spellbook_database
from mtg_analyzer.api.schemas import ComboAnalysisRequest
from mtg_analyzer.services.commander_spellbook_database import CommanderSpellbookDatabase

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/combos", tags=["combos"])


def _update(database: CommanderSpellbookDatabase) -> dict[str, object]:
    try:
        return database.update()
    except httpx.HTTPError as exc:
        logger.warning("Commander Spellbook download failed: %s", exc)
        raise HTTPException(
            status_code=502,
            detail="Commander Spellbook could not be reached; the existing combo database was kept.",
        ) from exc
    except (OSError, ValueError) as exc:
        logger.exception("Commander Spellbook snapshot could not be imported.")
        raise HTTPException(
            status_code=502,
            detail="The downloaded Commander Spellbook data could not be imported; the existing database was kept.",
        ) from exc


@router.get("/status")
def combo_database_status(
    database: CommanderSpellbookDatabase = Depends(get_commander_spellbook_database),
) -> dict[str, object]:
    return database.status()


@router.post("/update")
def update_combo_database(
    database: CommanderSpellbookDatabase = Depends(get_commander_spellbook_database),
) -> dict[str, object]:
    return _update(database)


@router.post("/matches")
def match_deck_combos(
    request: ComboAnalysisRequest,
    database: CommanderSpellbookDatabase = Depends(get_commander_spellbook_database),
) -> dict[str, object]:
    try:
        database.ensure_initialized()
        analysis = database.analyze_deck(
            [{"name": card.name, "quantity": card.quantity} for card in request.cards],
            include_recommendations=True,
            allowed_color_identity=request.color_identity,
        )
    except (httpx.HTTPError, OSError, ValueError) as exc:
        logger.warning("Commander Spellbook initial download failed: %s", exc)
        raise HTTPException(
            status_code=502,
            detail="The combo database could not be initialized or queried; retry after checking the server connection.",
        ) from exc
    return {**analysis, "database": database.status()}
