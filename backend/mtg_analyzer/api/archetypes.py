"""Archetype catalogue + archetype-likelihood analysis endpoints.

* ``GET  /api/archetypes``          — the full catalogue (id/label/
                                       description/...), for the deck-edit
                                       archetype picker and for label
                                       lookups (saved-decks-list badges).
* ``POST /api/archetypes/analyze``  — resolve a deck (same `deckId`-or-text
                                       shape as `api/dynamic_analysis.py`)
                                       and score it against the catalogue.

Reference: `mtg_analyzer/data/archetypes.json`, `services/
archetype_database.py`, `services/archetype_analysis.py`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from mtg_analyzer.api.dependencies import get_deck_database, get_lazy_card_loader
from mtg_analyzer.api.game import expand_entries
from mtg_analyzer.api.schemas import ArchetypeAnalysisRequest
from mtg_analyzer.parser.deckliste_parser import parse_deck_sections
from mtg_analyzer.services.archetype_analysis import detect_typal_signals, score_archetypes
from mtg_analyzer.services.archetype_database import default_archetype_database
from mtg_analyzer.services.deck_database import DeckDatabase
from mtg_analyzer.services.lazy_card_loader import LazyCardLoader

router = APIRouter(prefix="/api/archetypes", tags=["archetypes"])


@router.get("")
def list_archetypes() -> list[dict[str, object]]:
    return default_archetype_database().all_archetypes()


@router.post("/analyze")
def analyze_archetypes(
    request: ArchetypeAnalysisRequest,
    decks: DeckDatabase = Depends(get_deck_database),
    loader: LazyCardLoader = Depends(get_lazy_card_loader),
) -> dict[str, object]:
    """Resolve the deck (saved `deckId` or raw text, same as `api/
    dynamic_analysis.py`'s endpoint) and score it against the archetype
    catalogue."""
    commander_text = request.commander_text
    mainboard_text = request.mainboard_text
    sideboard_text = request.sideboard_text

    if request.deck_id:
        deck = decks.get_deck(request.deck_id)
        if deck is None:
            raise HTTPException(404, f'No saved deck with id "{request.deck_id}"')
        commander_text = deck.commander_text
        mainboard_text = deck.mainboard_text
        sideboard_text = deck.sideboard_text

    parsed = parse_deck_sections(commander_text, mainboard_text, sideboard_text)
    resolved = loader.load_cards([e.name for e in parsed.commanders] + [e.name for e in parsed.all_cards])

    library, _missing_lib = expand_entries(parsed.main_deck, resolved.cards)
    commanders, _missing_cmd = expand_entries(parsed.commanders, resolved.cards)
    cards = library + commanders

    return {
        "suggestions": [s.to_dict() for s in score_archetypes(cards)],
        "typalSignals": [s.to_dict() for s in detect_typal_signals(cards)],
    }
