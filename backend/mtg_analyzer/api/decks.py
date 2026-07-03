"""POST /api/decks: parse + structurally validate a decklist server-side.

Reference: backend/TODO.md "HTTP API foundation".
"""

from __future__ import annotations

from fastapi import APIRouter

from mtg_analyzer.api.schemas import DeckSubmission
from mtg_analyzer.parser.deckliste_parser import parse_deck_sections

router = APIRouter(prefix="/api", tags=["decks"])


@router.post("/decks")
def submit_deck(submission: DeckSubmission) -> dict[str, object]:
    parsed = parse_deck_sections(
        commander_text=submission.commander_text,
        mainboard_text=submission.mainboard_text,
        sideboard_text=submission.sideboard_text,
    )
    return parsed.to_dict()
