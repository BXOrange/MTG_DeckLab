"""POST /api/decks: parse + validate a decklist server-side.

Reference: docs/implementation-state/Done_Backend.md "HTTP API foundation".
"""

from __future__ import annotations

import httpx2 as httpx
from fastapi import APIRouter, Depends

from mtg_analyzer.api.dependencies import get_deck_database, get_lazy_card_loader, get_scryfall
from mtg_analyzer.api.schemas import DeckSubmission
from mtg_analyzer.services.deck_database import DeckDatabase
from mtg_analyzer.services.deck_printings import import_deck_printings
from mtg_analyzer.services.scryfall_client import ScryfallIntegration
from mtg_analyzer.services.deck_validation import validate_deck_sections
from mtg_analyzer.services.lazy_card_loader import LazyCardLoader

router = APIRouter(prefix="/api", tags=["decks"])


@router.post("/decks")
def submit_deck(
    submission: DeckSubmission,
    loader: LazyCardLoader = Depends(get_lazy_card_loader),
    database: DeckDatabase = Depends(get_deck_database),
    scryfall: ScryfallIntegration = Depends(get_scryfall),
) -> dict[str, object]:
    parsed = validate_deck_sections(
        submission.commander_text,
        submission.mainboard_text,
        submission.sideboard_text,
        loader,
        submission.is_cube,
    )
    result = parsed.to_dict()
    if submission.resolve_printings and parsed.printing_hints:
        codes = list(dict.fromkeys(parsed.printing_hints.values()))
        try:
            data = scryfall.fetch_printings_by_code(codes)
        except httpx.HTTPError:
            data = []
        printings, missing = import_deck_printings(parsed.printing_hints, data, database)
        result["cardPrintings"] = printings
        result["unresolvedPrintings"] = missing
    return result
