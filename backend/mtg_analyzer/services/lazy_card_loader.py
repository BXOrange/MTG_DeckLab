"""Load cards by name, fetching from Scryfall only for cards not yet cached.

Reference: docs/concepts/06_CARD_GRAPHICS_AND_LAZY_LOADING.md (PART 3),
docs/implementation-state/IMPLEMENTATION_GUIDE.md (Week 2, Day 4-5, "LazyCardLoader").
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.services.card_database import CardDatabase
from mtg_analyzer.services.scryfall_client import (
    ScryfallIntegration,
    ScryfallNotFoundError,
    card_from_scryfall_data,
)

#: The face separator in a multi-faced card name. Canonically Scryfall
#: writes " // ", but decklists and hand-typed lists use single-slash and
#: no-space variants too ("A // B", "A/B", "A / B"). No MTG card name
#: contains a lone "/" other than as this separator, so splitting on any
#: run of slashes is safe.
_FACE_SEPARATOR_RE = re.compile(r"\s*/+\s*")


@dataclass
class LoadCardsResult:
    """Cards found (in DB already or freshly fetched), plus any unknown names."""

    cards: dict[str, Card] = field(default_factory=dict)
    not_found: list[str] = field(default_factory=list)


class LazyCardLoader:
    """Resolves card names to `Card` objects, populating the DB on first use.

    `scryfall_primary` (see `mtg_analyzer/config.py`'s `SCRYFALL_PRIMARY` /
    `setup/start.py --scryfall-primary`) governs the loading *policy* for a
    name that's already cached — a name that's never been cached at all is
    always fetched once regardless, since there's no cached value to
    prefer. Default `False` ("cache-primary"): an already-cached row is
    served as-is even if it looks `stale` (see `_is_stale` below), so an
    ordinary load never makes a surprise Scryfall call for a card it's
    already seen. `True` ("scryfall-primary") restores this project's
    original behavior of always refetching a stale row to prefer Scryfall's
    current data.
    """

    def __init__(
        self,
        database: CardDatabase,
        scryfall: ScryfallIntegration,
        scryfall_primary: bool = False,
    ) -> None:
        self._database = database
        self._scryfall = scryfall
        self._scryfall_primary = scryfall_primary
        # `LazyCardLoader` is a process-wide singleton (`api/dependencies.py`'s
        # `@lru_cache`), so two concurrent `load_cards` calls resolving
        # overlapping decklists (e.g. two different saved decks that share a
        # staple, both requested via the frontend's per-deck `Promise.all` —
        # see saved_decks.py) could each independently see the same name as
        # a cache miss and both fetch-and-save it, duplicating Scryfall
        # traffic for no reason. Serializing the whole method under one lock
        # makes the miss-check and the fetch-and-save atomic together, so
        # the second caller sees the first one's freshly-saved row instead
        # of racing it. The method is fast for the (dominant) all-cache-hit
        # case — pure local SQLite reads — so this doesn't meaningfully
        # serialize unrelated work, only the genuinely-contended path.
        self._lock = threading.Lock()

    def load_cards(self, names: list[str]) -> LoadCardsResult:
        """Look up each name in the DB first; fetch only what's missing from Scryfall."""
        with self._lock:
            return self._load_cards_locked(names)

    def _load_cards_locked(self, names: list[str]) -> LoadCardsResult:
        result = LoadCardsResult()
        missing: list[str] = []
        #: Cached rows missing `mana_cost_string` (predate that field, or
        #: entered the cache some other way, e.g. a docs/08 import of an
        #: old export) — refetched below like a genuine miss, but kept
        #: here so a failed refetch still falls back to the stale copy
        #: rather than turning a previously-working card into "not found".
        stale: dict[str, Card] = {}

        for name in _dedupe(names):
            cached = self._database.get_card(name)
            if cached is None:
                missing.append(name)
            elif not self._scryfall_primary or _is_fresh(cached):
                result.cards[name] = cached
            else:
                # scryfall_primary=True only: refetch rows missing either
                # mana-cost or image data — the latter catches double-faced
                # cards cached before their per-face image URLs were
                # captured (see Card.has_image_data) — or still carrying a
                # pre-fix "Partner with X" reminder-text tail (see
                # Card.has_clean_partner_with).
                missing.append(name)
                stale[name] = cached

        if missing:
            # Scryfall's /cards/collection matches a double-faced card by a
            # *face* name, and reports the full "Front // Back" combined
            # name as not_found (verified against the live API for split
            # cards, MDFCs and pathways, e.g. "Wear // Tear"). Decklists,
            # meanwhile, write these both ways — the full combined name or
            # the front face alone. So always query Scryfall by the front
            # face, then map each result back to whatever name was
            # requested (full or front-face), keeping a query→requested
            # map so genuine misses are still reported under the asked name.
            query_names: list[str] = []
            requested_by_query: dict[str, list[str]] = {}
            for name in missing:
                query = _front_face_name(name)
                query_names.append(query)
                requested_by_query.setdefault(query.lower(), []).append(name)

            fetched_data, not_found = self._scryfall.fetch_multiple(_dedupe(query_names))
            cards_by_name: dict[str, Card] = {}
            for data in fetched_data:
                card = card_from_scryfall_data(data)
                self._database.save_card(card)
                cards_by_name[card.name.lower()] = card
                front_face = _front_face_name(card.name)
                if front_face != card.name:
                    cards_by_name.setdefault(front_face.lower(), card)

            # /cards/collection only matches a card's real (Oracle) name.
            # Some promo printings (Secret Lair's "Godzilla" series, several
            # Universes Beyond crossovers) are decklisted under their printed
            # *flavor name* instead (e.g. "Godzilla, King of the Monsters"
            # for Zilortha, Strength Incarnate) — verified against the live
            # API: /cards/collection reports these as not_found, but
            # /cards/named resolves them fine. Retry each apparent miss
            # there individually, keyed under the name as requested (the
            # resolved card's own Oracle name won't match it, so it can't
            # just fall into `cards_by_name` the normal way above).
            still_not_found: list[str] = []
            for query in not_found:
                try:
                    data = self._scryfall.fetch_card(query)
                except ScryfallNotFoundError:
                    still_not_found.append(query)
                    continue
                card = card_from_scryfall_data(data)
                self._database.save_card(card)
                cards_by_name[query.lower()] = card
            not_found = still_not_found

            for requested_name in missing:
                card = cards_by_name.get(requested_name.lower()) or cards_by_name.get(
                    _front_face_name(requested_name).lower()
                )
                if card is not None:
                    result.cards[requested_name] = card

            # Report genuinely-unknown cards under the caller's own name.
            for missing_query in not_found:
                for requested_name in requested_by_query.get(missing_query.lower(), []):
                    if requested_name not in result.cards:
                        result.not_found.append(requested_name)

        # A stale row's refetch didn't come back (rare — the card was
        # resolvable before) — keep serving the old copy rather than
        # newly reporting a previously-working card as not found.
        for name, cached in stale.items():
            if name not in result.cards:
                result.cards[name] = cached
                if name in result.not_found:
                    result.not_found.remove(name)

        return result


def _is_fresh(card: Card) -> bool:
    """Whether a cached row has all the data a full Scryfall lookup gives it.

    Only consulted in `scryfall_primary=True` mode — see `LazyCardLoader`.
    """
    return card.has_mana_cost_data and card.has_image_data and card.has_clean_partner_with


def _front_face_name(name: str) -> str:
    """The front-face name of a multi-faced card, else `name` unchanged.

    Tolerates the canonical " // " as well as the single-slash / no-space
    variants ("A/B", "A / B") that turn up in real decklists — e.g.
    "Halvar, God of Battle / Sword of the Realms" — so those resolve too.
    """
    return _FACE_SEPARATOR_RE.split(name, maxsplit=1)[0].strip()


def _dedupe(names: list[str]) -> list[str]:
    seen: dict[str, None] = {}
    for name in names:
        seen.setdefault(name, None)
    return list(seen.keys())
