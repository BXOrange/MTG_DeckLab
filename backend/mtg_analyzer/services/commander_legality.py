"""Commander-specific legality checks that need real card data.

Structural checks (card count, singleton, commander count) live in
mtg_analyzer/parser/deckliste_parser.py and only need names/quantities
from the raw decklist text. Color identity, the banned-card list, and
the Partner mechanic need resolved `Card` data instead (color_identity,
oracle-text-derived has_partner/partner_with), so this runs as a second
pass in mtg_analyzer/api/decks.py, once names are resolved via the
LazyCardLoader.

Reference: backend/ToDo_Backend.md "Validator".
"""

from __future__ import annotations

from mtg_analyzer.models.card import Card

#: Commander-format banned list, maintained by hand — Scryfall's
#: per-printing `legalities` field isn't fetched today (see
#: scryfall_client.card_from_scryfall_data), so there's no live source
#: to derive this from. Deliberately conservative: only long-standing
#: entries that have survived the format's various unban waves are
#: listed. Verify against https://mtgcommander.net/index.php/banned-list/
#: before relying on this for anything but a rough sanity check, and
#: update it there when the committee announces changes.
BANNED_COMMANDER_CARDS: frozenset[str] = frozenset(
    {
        "Ancestral Recall",
        "Balance",
        "Biorhythm",
        "Black Lotus",
        "Braids, Cabal Minion",
        "Channel",
        "Chaos Orb",
        "Coalition Victory",
        "Emrakul, the Aeons Torn",
        "Erayo, Soratami Ascendant",
        "Falling Star",
        "Fastbond",
        "Flash",
        "Gifts Ungiven",
        "Golos, Tireless Pilgrim",
        "Griselbrand",
        "Iona, Shield of Emeria",
        "Leovold, Emissary of Trest",
        "Library of Alexandria",
        "Lutri, the Spellchaser",
        "Mox Emerald",
        "Mox Jet",
        "Mox Pearl",
        "Mox Ruby",
        "Mox Sapphire",
        "Nadu, Winged Wisdom",
        "Paradox Engine",
        "Time Walk",
        "Tolarian Academy",
        "Trade Secrets",
    }
)


def check_commander_legality(commanders: list[Card], deck_cards: list[Card]) -> list[str]:
    """Check the ban list, color identity, and Partner rules; return error strings.

    `commanders` must be the deck's complete, fully-resolved commander
    set. Callers should skip calling this entirely (rather than passing
    a partial set) if any commander name failed to resolve — an
    incomplete commander list understates the deck's true color
    identity and would produce false color-identity violations.
    `deck_cards` is expected to already include the commanders (as
    `ParsedDeck.all_cards` does), so their own color identity and ban
    status are checked as a side effect of checking every other card.
    """
    errors: list[str] = []

    _check_banned(deck_cards, errors)
    _check_color_identity(commanders, deck_cards, errors)
    if len(commanders) == 2:
        _check_partner(commanders, errors)

    return errors


def _check_banned(deck_cards: list[Card], errors: list[str]) -> None:
    names = sorted({card.name for card in deck_cards if card.name in BANNED_COMMANDER_CARDS})
    for name in names:
        errors.append(f'"{name}" ist im Commander-Format auf der Bannliste.')


def _check_color_identity(commanders: list[Card], deck_cards: list[Card], errors: list[str]) -> None:
    if not commanders:
        return

    identity: set[str] = set()
    for commander in commanders:
        identity |= commander.color_identity
    identity_label = "/".join(sorted(identity)) if identity else "farblos"

    for card in deck_cards:
        outside = card.color_identity - identity
        if outside:
            errors.append(
                f'"{card.name}" ({"/".join(sorted(card.color_identity))}) liegt außerhalb '
                f"der Farbidentität des Commanders ({identity_label})."
            )


def _check_partner(commanders: list[Card], errors: list[str]) -> None:
    first, second = commanders
    if not _can_pair(first, second):
        errors.append(
            f'"{first.name}" und "{second.name}" können nicht gemeinsam Commander sein '
            "(keine passende Partner-Fähigkeit)."
        )


def _can_pair(first: Card, second: Card) -> bool:
    """Whether two cards may legally be paired as co-commanders.

    "Partner with X" is a distinct, more restrictive ability from plain
    "Partner": it only pairs with the specifically named card (and that
    card must name it back), not with any other Partner card. Plain
    Partner pairs with any other plain-Partner card. Both `has_partner`
    and `partner_with` get set for "Partner with X" cards (see
    scryfall_client._has_partner), so `partner_with` must be checked
    first.
    """
    if first.partner_with or second.partner_with:
        return (
            first.partner_with is not None
            and second.partner_with is not None
            and first.partner_with.strip().lower() == second.name.strip().lower()
            and second.partner_with.strip().lower() == first.name.strip().lower()
        )
    return first.has_partner and second.has_partner
