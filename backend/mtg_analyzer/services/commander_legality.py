"""Commander-specific legality checks that need real card data.

Structural checks (card count, singleton, commander count) live in
mtg_analyzer/parser/deckliste_parser.py and only need names/quantities
from the raw decklist text. Color identity, the banned-card list, and
the Partner mechanic need resolved `Card` data instead (color_identity,
oracle-text-derived has_partner/partner_with), so this runs as a second
pass in mtg_analyzer/api/decks.py, once names are resolved via the
LazyCardLoader.

Reference: docs/implementation-state/Done_Backend.md "Validator".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from mtg_analyzer.models.cards.card import Card

#: RULE 903.3: a card whose own oracle text grants commander eligibility
#: without being legendary (older planeswalkers printed before the
#: Legendary Planeswalker supertype existed, and a handful of un-set/
#: Signature Spellbook-style cards).
_CAN_BE_COMMANDER_RE = re.compile(r"can be your commander", re.IGNORECASE)
#: RULE 903.3d — printed on the creature half of a "Choose a Background"
#: pair, e.g. "Choose a Background (You can choose a Background as one
#: of your two commanders.)".
_CHOOSE_BACKGROUND_RE = re.compile(r"^Choose a Background\b", re.MULTILINE)
#: RULE 702.123i-adjacent "Friends forever" — pairs with any other
#: Friends-forever card, same shape as plain Partner.
_FRIENDS_FOREVER_RE = re.compile(r"^Friends forever\b", re.MULTILINE)

#: Commander-format banned list. A frozen snapshot of Scryfall's
#: `legalities.commander` field (that field isn't part of the app-facing
#: `Card` model — see scryfall_client.card_from_scryfall_data — so this
#: constant is the only place the app can check a ban against). Kept in
#: sync with `scripts/update_ban_lists.py`, which rewrites this exact
#: literal from the persistent raw card store; don't hand-edit it, and
#: don't reformat it, since the round-trip check that script does after
#: writing depends on this shape. `scripts/update_card_pool.py` prints a
#: heads-up diff on every routine refresh; run `update_ban_lists.py`
#: to apply it.
BANNED_COMMANDER_CARDS: frozenset[str] = frozenset(
    {
        "Adriana's Valor",
        'Advantageous Proclamation',
        'Amulet of Quoz',
        'Ancestral Recall',
        'Assemble the Rank and Vile',
        'Backup Plan',
        'Balance',
        'Black Lotus',
        "Brago's Favor",
        'Bronze Tablet',
        'Channel',
        'Chaos Orb',
        'Cleanse',
        'Contract from Below',
        'Crusade',
        'Darkpact',
        'Demonic Attorney',
        'Dockside Extortionist',
        'Double Stroke',
        'Echoing Boon',
        "Emissary's Ploy",
        'Emrakul, the Aeons Torn',
        "Erayo, Soratami Ascendant // Erayo's Essence",
        'Falling Star',
        'Fastbond',
        'Flash',
        'Golos, Tireless Pilgrim',
        'Griselbrand',
        'Hired Heist',
        'Hold the Perimeter',
        'Hullbreacher',
        'Hymn of the Wilds',
        'Immediate Action',
        'Imprison',
        'Incendiary Dissent',
        'Invoke Prejudice',
        'Iona, Shield of Emeria',
        'Iterative Analysis',
        'Jeweled Bird',
        'Jeweled Lotus',
        'Jihad',
        'Karakas',
        'Leovold, Emissary of Trest',
        'Library of Alexandria',
        'Limited Resources',
        'Mana Crypt',
        'Mox Emerald',
        'Mox Jet',
        'Mox Pearl',
        'Mox Ruby',
        'Mox Sapphire',
        "Muzzio's Preparations",
        'Nadu, Winged Wisdom',
        'Natural Unity',
        'Paradox Engine',
        'Power Play',
        'Pradesh Gypsies',
        'Primeval Titan',
        'Prophet of Kruphix',
        'Rebirth',
        'Recurring Nightmare',
        'Rofellos, Llanowar Emissary',
        'Secret Summoning',
        'Secrets of Paradise',
        'Sentinel Dispatch',
        'Shahrazad',
        "Sovereign's Realm",
        'Stone-Throwing Devils',
        "Summoner's Bond",
        'Sundering Titan',
        'Sylvan Primordial',
        'Tempest Efreet',
        'Time Vault',
        'Time Walk',
        'Timmerian Fiends',
        'Tinker',
        'Tolarian Academy',
        'Trade Secrets',
        'Unexpected Potential',
        'Upheaval',
        'Weight Advantage',
        'Worldknit',
        "Yawgmoth's Bargain",
    }
)


@dataclass
class CommanderLegalityResult:
    """Human-readable errors plus which specific card names to flag and
    why, so a caller (the frontend) can mark individual cards without
    parsing prose error messages. A name can appear in both
    `banned_card_names` and `color_identity_violation_names`.
    """

    errors: list[str] = field(default_factory=list)
    banned_card_names: list[str] = field(default_factory=list)
    color_identity_violation_names: list[str] = field(default_factory=list)


def check_commander_legality(
    commanders: list[Card], deck_cards: list[Card]
) -> CommanderLegalityResult:
    """Check the ban list, color identity, legendary status, and the
    Partner/Friends-forever/Background pairing rules.

    `commanders` must be the deck's complete, fully-resolved commander
    set. Callers should skip calling this entirely (rather than passing
    a partial set) if any commander name failed to resolve — an
    incomplete commander list understates the deck's true color
    identity and would produce false color-identity violations.
    `deck_cards` is expected to already include the commanders (as
    `ParsedDeck.all_cards` does), so their own color identity and ban
    status are checked as a side effect of checking every other card.
    """
    result = CommanderLegalityResult()

    _check_banned(deck_cards, result)
    _check_color_identity(commanders, deck_cards, result)
    _check_legendary(commanders, result)
    if len(commanders) == 2:
        _check_pairing(commanders, result)

    return result


def _check_banned(deck_cards: list[Card], result: CommanderLegalityResult) -> None:
    names = sorted({card.name for card in deck_cards if card.name in BANNED_COMMANDER_CARDS})
    for name in names:
        result.errors.append(f'"{name}" ist im Commander-Format auf der Bannliste.')
        result.banned_card_names.append(name)


def _check_color_identity(
    commanders: list[Card], deck_cards: list[Card], result: CommanderLegalityResult
) -> None:
    if not commanders:
        return

    identity: set[str] = set()
    for commander in commanders:
        identity |= commander.color_identity
    identity_label = "/".join(sorted(identity)) if identity else "farblos"

    for card in deck_cards:
        outside = card.color_identity - identity
        if outside:
            result.errors.append(
                f'"{card.name}" ({"/".join(sorted(card.color_identity))}) liegt außerhalb '
                f"der Farbidentität des Commanders ({identity_label})."
            )
            result.color_identity_violation_names.append(card.name)


def _check_legendary(commanders: list[Card], result: CommanderLegalityResult) -> None:
    """RULE 903.3: each commander must be legendary, a card whose text
    says it can be your commander, or — the one legal non-legendary
    case — a Background enchantment correctly paired with a "Choose a
    Background" creature (a lone or wrongly-paired Background is still
    flagged, since its commander eligibility only exists as half of that
    pair).
    """
    background_pair_ok = len(commanders) == 2 and _can_pair_background(*commanders)
    for card in commanders:
        if _is_legendary(card):
            continue
        if _CAN_BE_COMMANDER_RE.search(card.oracle_text or ""):
            continue
        if _is_background(card) and background_pair_ok:
            continue
        result.errors.append(
            f'"{card.name}" ist nicht legendär und kann daher nicht Commander sein.'
        )


def _check_pairing(commanders: list[Card], result: CommanderLegalityResult) -> None:
    first, second = commanders
    if not _can_pair(first, second):
        result.errors.append(
            f'"{first.name}" und "{second.name}" können nicht gemeinsam Commander sein '
            "(keine passende Partner-Fähigkeit)."
        )


def _can_pair(first: Card, second: Card) -> bool:
    """Whether two cards may legally be paired as co-commanders: plain
    Partner, "Partner with X", Friends forever, or a "Choose a
    Background" creature with an actual Background enchantment.
    """
    return (
        _can_pair_partner(first, second)
        or (_has_friends_forever(first) and _has_friends_forever(second))
        or _can_pair_background(first, second)
    )


def _can_pair_partner(first: Card, second: Card) -> bool:
    """"Partner with X" is a distinct, more restrictive ability from plain
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


def _can_pair_background(first: Card, second: Card) -> bool:
    """RULE 903.3d: a "Choose a Background" creature pairs only with an
    actual Background enchantment, never with another Partner/Friends-
    forever card. Background is a card subtype rather than a keyword
    ability, so the Background half is recognized by its type line
    instead of by oracle text.
    """
    return (_has_choose_background(first) and _is_background(second)) or (
        _has_choose_background(second) and _is_background(first)
    )


def _has_choose_background(card: Card) -> bool:
    return bool(_CHOOSE_BACKGROUND_RE.search(card.oracle_text or ""))


def _has_friends_forever(card: Card) -> bool:
    return bool(_FRIENDS_FOREVER_RE.search(card.oracle_text or ""))


def _is_background(card: Card) -> bool:
    return "background" in card.type_line.lower()


def _is_legendary(card: Card) -> bool:
    """Read off the type line rather than `Card.is_legendary` directly:
    every real production source (`scryfall_client`, `token_database`)
    keeps that stored flag in sync with the printed "Legendary"
    supertype, but this project's own hand-built `Card(...)` test
    fixtures frequently don't bother setting it even when their
    `type_line` says "Legendary" — matching `is_planeswalker`/
    `is_artifact`'s type-line-derived pattern instead avoids that whole
    class of false negative.
    """
    return card.is_legendary or "legendary" in card.type_line.lower()
