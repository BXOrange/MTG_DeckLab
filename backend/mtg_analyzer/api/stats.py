"""Lightweight aggregate counts for the DeckLab home page."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from typing import Optional

from mtg_analyzer.api.auth import AuthContext, current_context
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
    ctx: Optional[AuthContext] = Depends(current_context),
) -> dict[str, int]:
    """Return cached-card, saved-deck and connected-human counts.

    The deck count is what the caller may read (global + own private); anonymous callers
    see the global decks only (PLR-9b).
    """
    return {
        "cards": cards.count(),
        "decks": decks.count(ctx.account.player_uuid if ctx else None),
        "players": sum(player.connected for player in lobby.players()),
    }
