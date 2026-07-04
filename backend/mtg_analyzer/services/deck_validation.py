"""Shared deck legality validation: resolve cards + Commander checks.

Reference: backend/ToDo_Backend.md "Validator", docs/02 UC1.

`POST /api/decks`, `GET /api/decks/{id}/validation`, and starting a
goldfish game all need the same thing: take a parsed decklist, resolve
its cards, and fill in real Commander legality (color identity, ban list,
partner). This centralizes that so the three call sites can't drift.
"""

from __future__ import annotations

from mtg_analyzer.parser.deckliste_parser import ParsedDeck, parse_deck_sections
from mtg_analyzer.services.commander_legality import check_commander_legality
from mtg_analyzer.services.lazy_card_loader import LazyCardLoader, LoadCardsResult


def apply_legality(parsed: ParsedDeck, resolved: LoadCardsResult) -> ParsedDeck:
    """Fill ``parsed.validation`` with real Commander legality (mutates it).

    Uses already-resolved card data so a caller that resolved for another
    reason (e.g. building a game) needn't resolve twice. An incomplete
    commander set (a commander name that failed to resolve) would
    understate color identity and produce false violations, so the real
    checks only run once every commander is known.
    """
    commander_names = [entry.name for entry in parsed.commanders]
    all_names = [entry.name for entry in parsed.all_cards]

    commanders_resolved = [resolved.cards[n] for n in commander_names if n in resolved.cards]
    deck_cards_resolved = [resolved.cards[n] for n in all_names if n in resolved.cards]

    if commanders_resolved and len(commanders_resolved) == len(commander_names):
        legality = check_commander_legality(commanders_resolved, deck_cards_resolved)
        parsed.validation.errors.extend(legality.errors)
        parsed.validation.banned_card_names = legality.banned_card_names
        parsed.validation.color_identity_violation_names = legality.color_identity_violation_names

    if resolved.not_found:
        parsed.validation.warnings.append(
            "Kartendaten nicht gefunden, Farbidentität/Bannliste nicht geprüft für: "
            + ", ".join(sorted(set(resolved.not_found)))
        )

    parsed.validation.is_legal = not parsed.validation.errors
    return parsed


def validate_deck_sections(
    commander_text: str, mainboard_text: str, sideboard_text: str, loader: LazyCardLoader
) -> ParsedDeck:
    """Parse + resolve + validate a decklist in one call."""
    parsed = parse_deck_sections(commander_text, mainboard_text, sideboard_text)
    resolved = loader.load_cards(
        [e.name for e in parsed.commanders] + [e.name for e in parsed.all_cards]
    )
    return apply_legality(parsed, resolved)
