"""POST /api/decks: parse + validate a decklist server-side.

Reference: backend/ToDo_Backend.md "HTTP API foundation".
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from mtg_analyzer.api.dependencies import get_lazy_card_loader
from mtg_analyzer.api.schemas import DeckSubmission
from mtg_analyzer.services.deck_validation import validate_deck_sections
from mtg_analyzer.services.lazy_card_loader import LazyCardLoader

router = APIRouter(prefix="/api", tags=["decks"])


@router.post("/decks")
def submit_deck(
    submission: DeckSubmission,
    loader: LazyCardLoader = Depends(get_lazy_card_loader),
) -> dict[str, object]:
    parsed = validate_deck_sections(
        submission.commander_text,
        submission.mainboard_text,
        submission.sideboard_text,
        loader,
    )
    return parsed.to_dict()
