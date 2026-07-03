"""Load cards by name, fetching from Scryfall only for cards not yet cached.

Reference: docs/06_CARD_GRAPHICS_AND_LAZY_LOADING.md (PART 3),
docs/IMPLEMENTATION_GUIDE.md (Week 2, Day 4-5, "LazyCardLoader").
"""

from __future__ import annotations

from dataclasses import dataclass, field

from mtg_analyzer.models.card import Card
from mtg_analyzer.services.card_database import CardDatabase
from mtg_analyzer.services.scryfall_client import ScryfallIntegration, card_from_scryfall_data


@dataclass
class LoadCardsResult:
    """Cards found (in DB already or freshly fetched), plus any unknown names."""

    cards: dict[str, Card] = field(default_factory=dict)
    not_found: list[str] = field(default_factory=list)


class LazyCardLoader:
    """Resolves card names to `Card` objects, populating the DB on first use."""

    def __init__(self, database: CardDatabase, scryfall: ScryfallIntegration) -> None:
        self._database = database
        self._scryfall = scryfall

    def load_cards(self, names: list[str]) -> LoadCardsResult:
        """Look up each name in the DB first; fetch only what's missing from Scryfall."""
        result = LoadCardsResult()
        missing: list[str] = []

        for name in _dedupe(names):
            cached = self._database.get_card(name)
            if cached is not None:
                result.cards[name] = cached
            else:
                missing.append(name)

        if missing:
            fetched_data, not_found = self._scryfall.fetch_multiple(missing)
            cards_by_name = {}
            for data in fetched_data:
                card = card_from_scryfall_data(data)
                self._database.save_card(card)
                cards_by_name[card.name.lower()] = card

            for requested_name in missing:
                card = cards_by_name.get(requested_name.lower())
                if card is not None:
                    result.cards[requested_name] = card
            result.not_found.extend(not_found)

        return result


def _dedupe(names: list[str]) -> list[str]:
    seen: dict[str, None] = {}
    for name in names:
        seen.setdefault(name, None)
    return list(seen.keys())
