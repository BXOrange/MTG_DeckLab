"""Server-side decklist parser and structural Commander validator.

Mirrors frontend/src/js/parser.js line for line so the same rules apply
whether a decklist is checked client-side or through POST /api/decks.
This covers the parsing half of the Phase 1 DecklisteParser task
(docs/IMPLEMENTATION_GUIDE.md Week 1 Day 3-5); real Commander legality
(color identity, ban list, partner rules) is intentionally out of scope
here because it needs card data from the CardDatabase, which doesn't
exist yet (see backend/Done_Backend.md "Validator").
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

#: Basic lands (including snow-covered) are exempt from the singleton rule.
BASIC_LAND_NAMES: frozenset[str] = frozenset(
    {
        "Plains",
        "Island",
        "Swamp",
        "Mountain",
        "Forest",
        "Wastes",
        "Snow-Covered Plains",
        "Snow-Covered Island",
        "Snow-Covered Swamp",
        "Snow-Covered Mountain",
        "Snow-Covered Forest",
        "Snow-Covered Wastes",
    }
)

_CARD_LINE_RE = re.compile(r"^(\d+)\s*[xX]?\s+(.+)$")
_SET_SUFFIX_RE = re.compile(r"\s*[\[(][A-Za-z0-9]{2,6}[)\]]\s*[\dA-Za-z-]*\s*$")
_TAG_RE = re.compile(r"\s*\*([A-Za-z]+)\*")
#: Foil/star markers some exports append to a name (e.g. "Sol Ring ★").
#: They aren't part of the card name and break resolution, so strip them.
_STAR_RE = re.compile(r"[★☆]")


@dataclass
class CardEntry:
    """A single named card and how many copies were listed."""

    name: str
    qty: int

    def to_dict(self) -> dict[str, object]:
        return {"name": self.name, "qty": self.qty}


@dataclass
class DeckValidationResult:
    """Commander legality: structural checks here, plus color
    identity/ban-list/partner names filled in by
    mtg_analyzer.api.decks after card resolution (see
    services/commander_legality.py) — empty here since this module only
    has names/quantities, not resolved Card data.
    """

    is_legal: bool
    errors: list[str]
    warnings: list[str]
    banned_card_names: list[str] = field(default_factory=list)
    color_identity_violation_names: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "isLegal": self.is_legal,
            "errors": self.errors,
            "warnings": self.warnings,
            "bannedCardNames": self.banned_card_names,
            "colorIdentityViolationNames": self.color_identity_violation_names,
        }


@dataclass
class ParsedDeck:
    """Result of parsing a decklist split into commander/mainboard/sideboard."""

    commanders: list[CardEntry]
    main_deck: list[CardEntry]
    all_cards: list[CardEntry]
    sideboard: list[CardEntry]
    total_count: int
    parse_errors: list[str]
    validation: DeckValidationResult

    def to_dict(self) -> dict[str, object]:
        return {
            "commanders": [c.to_dict() for c in self.commanders],
            "mainDeck": [c.to_dict() for c in self.main_deck],
            "allCards": [c.to_dict() for c in self.all_cards],
            "sideboard": [c.to_dict() for c in self.sideboard],
            "totalCount": self.total_count,
            "parseErrors": self.parse_errors,
            "validation": self.validation.to_dict(),
        }


@dataclass
class _ParsedSection:
    cards: list[CardEntry] = field(default_factory=list)
    parse_errors: list[str] = field(default_factory=list)


def _parse_card_lines(raw_text: str) -> _ParsedSection:
    section = _ParsedSection()

    for raw_line in (raw_text or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("//"):
            continue

        match = _CARD_LINE_RE.match(line)
        if not match:
            section.parse_errors.append(f'Zeile konnte nicht gelesen werden: "{raw_line}"')
            continue

        qty = int(match.group(1))
        name = match.group(2).strip()
        name = _TAG_RE.sub("", name).strip()
        name = _SET_SUFFIX_RE.sub("", name).strip()
        name = _STAR_RE.sub("", name)
        name = re.sub(r"\s{2,}", " ", name).strip()

        if not name:
            section.parse_errors.append(f'Leerer Kartenname in Zeile: "{raw_line}"')
            continue

        section.cards.append(CardEntry(name=name, qty=qty))

    return section


def _merge_cards(cards: list[CardEntry]) -> list[CardEntry]:
    merged: dict[str, CardEntry] = {}
    for card in cards:
        key = card.name.lower()
        if key in merged:
            merged[key].qty += card.qty
        else:
            merged[key] = CardEntry(name=card.name, qty=card.qty)
    return list(merged.values())


def _validate_commander_deck(
    all_cards: list[CardEntry], commanders: list[CardEntry], total_count: int
) -> DeckValidationResult:
    errors: list[str] = []
    warnings: list[str] = []

    if not commanders:
        warnings.append('Kein Commander erkannt (im Abschnitt "Commander" eintragen).')
    elif len(commanders) > 2:
        errors.append(
            f"Zu viele Commander erkannt ({len(commanders)}). Erlaubt sind 1 (oder 2 mit Partner)."
        )

    if total_count != 100:
        errors.append(f"Deck hat {total_count} Karten, erwartet werden 100 (inkl. Commander).")

    for card in all_cards:
        if card.qty > 1 and card.name not in BASIC_LAND_NAMES:
            errors.append(
                f'"{card.name}" ist {card.qty}x im Deck – Commander ist Singleton (außer Basic Lands).'
            )

    return DeckValidationResult(is_legal=not errors, errors=errors, warnings=warnings)


def parse_deck_sections(
    commander_text: str = "", mainboard_text: str = "", sideboard_text: str = ""
) -> ParsedDeck:
    """Parse and structurally validate a decklist split into three sections.

    Card lines look like "4x Lightning Bolt" or "1 Sol Ring", with optional
    "*TAG*" markers and trailing set/collector info like "(LTR) 123"
    stripped. Blank lines and lines starting with "#" or "//" are ignored.
    """
    commander_parsed = _parse_card_lines(commander_text)
    mainboard_parsed = _parse_card_lines(mainboard_text)
    sideboard_parsed = _parse_card_lines(sideboard_text)

    parse_errors = [
        *commander_parsed.parse_errors,
        *mainboard_parsed.parse_errors,
        *sideboard_parsed.parse_errors,
    ]

    commanders = _merge_cards(commander_parsed.cards)
    main_deck = _merge_cards(mainboard_parsed.cards)
    sideboard = _merge_cards(sideboard_parsed.cards)
    all_cards = _merge_cards([*commander_parsed.cards, *mainboard_parsed.cards])
    total_count = sum(c.qty for c in all_cards)

    validation = _validate_commander_deck(all_cards, commanders, total_count)

    return ParsedDeck(
        commanders=commanders,
        main_deck=main_deck,
        all_cards=all_cards,
        sideboard=sideboard,
        total_count=total_count,
        parse_errors=parse_errors,
        validation=validation,
    )
