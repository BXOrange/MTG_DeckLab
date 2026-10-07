"""Lightweight aggregate counts for the DeckLab home page."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from mtg_analyzer.api.dependencies import get_card_database, get_deck_database, get_lobby
from mtg_analyzer.services.card_database import CardDatabase
from mtg_analyzer.services.deck_database import DeckDatabase
from mtg_analyzer.services.lobby import Lobby

router = APIRouter(prefix="/api", tags=["overview"])


@router.get("/stats")
def overview_stats(
    cards: CardDatabase = Depends(get_card_database),
    decks: DeckDatabase = Depends(get_deck_database),
    lobby: Lobby = Depends(get_lobby),
) -> dict[str, int]:
    """Return cached-card, saved-deck and connected-human counts."""
    return {
        "cards": cards.count(),
        "decks": decks.count(),
        "players": sum(player.connected for player in lobby.players()),
    }
