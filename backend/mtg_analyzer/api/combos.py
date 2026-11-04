"""Local Commander Spellbook combo database API."""

from __future__ import annotations

import logging

import httpx2 as httpx
from fastapi import APIRouter, Depends

from mtg_analyzer.i18n import api_error
from mtg_analyzer.api.admin_auth import require_admin
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
        raise api_error(502, "combo_db_unreachable") from exc
    except (OSError, ValueError) as exc:
        logger.exception("Commander Spellbook snapshot could not be imported.")
        raise api_error(502, "combo_db_import_failed") from exc


@router.get("/status")
def combo_database_status(
    database: CommanderSpellbookDatabase = Depends(get_commander_spellbook_database),
) -> dict[str, object]:
    return database.status()


@router.post("/update", dependencies=[Depends(require_admin)])
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
        raise api_error(502, "combo_db_unavailable") from exc
    return {**analysis, "database": database.status()}
