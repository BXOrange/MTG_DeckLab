"""POST /api/decks: parse + validate a decklist server-side.

Reference: backend/ToDo_Backend.md "HTTP API foundation".
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from mtg_analyzer.api.dependencies import get_lazy_card_loader
from mtg_analyzer.api.schemas import DeckSubmission
from mtg_analyzer.parser.deckliste_parser import parse_deck_sections
from mtg_analyzer.services.commander_legality import check_commander_legality
from mtg_analyzer.services.lazy_card_loader import LazyCardLoader

router = APIRouter(prefix="/api", tags=["decks"])


@router.post("/decks")
def submit_deck(
    submission: DeckSubmission,
    loader: LazyCardLoader = Depends(get_lazy_card_loader),
) -> dict[str, object]:
    parsed = parse_deck_sections(
        commander_text=submission.commander_text,
        mainboard_text=submission.mainboard_text,
        sideboard_text=submission.sideboard_text,
    )

    commander_names = [entry.name for entry in parsed.commanders]
    all_names = [entry.name for entry in parsed.all_cards]
    resolved = loader.load_cards([*commander_names, *all_names])

    commanders_resolved = [
        resolved.cards[name] for name in commander_names if name in resolved.cards
    ]
    deck_cards_resolved = [resolved.cards[name] for name in all_names if name in resolved.cards]

    # An incomplete commander set (a commander name that failed to
    # resolve) would understate the deck's true color identity and
    # produce false violations, so only run the real legality checks
    # once every commander is known.
    if commanders_resolved and len(commanders_resolved) == len(commander_names):
        parsed.validation.errors.extend(
            check_commander_legality(commanders_resolved, deck_cards_resolved)
        )

    if resolved.not_found:
        parsed.validation.warnings.append(
            "Kartendaten nicht gefunden, Farbidentität/Bannliste nicht geprüft für: "
            + ", ".join(sorted(set(resolved.not_found)))
        )

    parsed.validation.is_legal = not parsed.validation.errors

    return parsed.to_dict()
