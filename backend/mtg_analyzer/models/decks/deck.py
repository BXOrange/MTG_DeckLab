"""Deck model: a saved decklist, identified by a UUID rather than its name.

Reference: docs/concepts/04_SERVER_CLIENT_ARCHITECTURE.md (PART 4, REST
endpoints), docs/implementation-state/Done_Backend.md "Deck persistence".
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional


class Deck:
    """A saved decklist.

    Identified by `id` (a UUID, generated automatically if not given).
    `name` is just a descriptive property, not a lookup key — two saved
    decks may share a name. Only the raw decklist text is stored (the
    same three sections `POST /api/decks` already accepts); it's
    re-parsed on demand rather than persisting derived data that could
    drift from the parser's actual current behavior.

    `analysis_id` links the current ANA-1 narrative result in analyses.db.
    Section/archetype edits invalidate the link; cosmetic edits preserve it.
    See docs/Reference/LLM_INTEGRATION.md for the API and cache contract.

    `sleeve_id` optionally references one of this deck owner's uploaded
    card-back designs (`services/player_assets.py`, `api/player_assets.py`
    `/api/players/{name}/sleeves`) — set via the saved-decks list, read by
    the goldfish board as the fallback "back of card" art for a face-down
    object with no real art of its own.

    `author` is a free-text, optional credit for who built the deck (may be
    empty/`None`) — purely descriptive, shown in the saved-decks list, set
    the same way `sleeve_id` is (edited from the saved-decks list, or at
    creation time).

    `is_cube` marks this decklist as a card pool ("cube") rather than a
    real, legal Commander deck — e.g. a curated "staples" reference list
    with hundreds of cards. When set, `services/deck_validation.py` skips
    both the structural Commander checks (100-card total, singleton,
    commander count — `parser/deckliste_parser.py`) and the semantic ones
    (ban list, color identity, Partner — `services/commander_legality.py`)
    entirely, rather than reporting a cube's inherent "violations" as
    errors. Defaults to `False` so every existing/ordinary deck keeps full
    validation.

    `archetypes` is 0-2 ids into the archetype catalogue
    (`services/archetype_database.py`, `data/archetypes.json`) the deck's
    owner has picked to describe its playstyle (Aristocrats, Voltron, ...) —
    purely descriptive, set from the deck-edit form. `None` means never
    set; `api/saved_decks.py`'s `save_deck` validates ids against the
    catalogue and caps the list at 2, same preserve-on-omission treatment
    as `sleeve_id`/`author`/`is_cube`.

    `favorite_cards` is a list of card names (not ids — no stable per-card
    id exists below deck level, matching `parser/deckliste_parser.py`'s
    `CardEntry.name` granularity) the owner starred in the deck-edit card
    grid. Feeds the dynamic-analysis "was this card drawn/cast/castable"
    breakdown (`services/dynamic_analysis.py`). Same preserve-on-omission
    treatment as the fields above.

    `color_identity`/`commanders` are derived from the decklist text (RULE
    903.4 for the color-identity definition) but, unlike everything else on
    this model, cached rather than re-derived on every read: computing them
    needs resolved `Card` data (a Scryfall/cache lookup per card), which is
    too costly to redo on every saved-decks list render. `None` means "not
    computed yet" (a fresh deck, or one whose decklist text changed since
    the last computation — `api/saved_decks.py` resets both to `None`
    whenever the text sections change); the endpoint that serves decks
    computes and persists them once they're needed, and leaves them alone
    otherwise. An empty list is a real, computed answer (a colorless deck /
    no commander section), distinct from "not computed yet".

    `validation_result`/`unmodeled_coverage` are the same caching pattern,
    for `GET /api/decks/{id}/validation` and `/coverage` — both also need a
    resolved `Card` per deck entry, and the frontend fires *both* endpoints
    for *every* saved deck in parallel whenever the saved-decks list or any
    of the three game-setup screens render (`savedDecksView.js`,
    `gameSetup.js`'s `loadUnmodeledDeckIds`), so leaving them uncached turned
    routine navigation into a full parse+resolve+validate pass over every
    card of every deck, every time — the concrete source of the Scryfall
    rate-limit bursts this caching was added to fix. `None` means "not
    computed yet"; `api/saved_decks.py` resets both to `None` in the exact
    same `save_deck` branch that already resets `color_identity`/
    `commanders` (decklist text changed) and additionally whenever `is_cube`
    changes, since that flag changes what `validation_result` itself means
    (RULE-checks skipped entirely for a cube). Each is stored as the plain
    JSON-shaped dict its endpoint already returns (`DeckValidationResult.
    to_dict()` / `{"unmodeledCount", "unmodeledCardNames"}`), not a richer
    object, so serving a cache hit is a pure dict return with no
    re-derivation at all. `unmodeled_coverage_version` records the oracle
    parser version used for that coverage calculation. A later parser change
    makes the cache stale even when the deck text itself is unchanged.
    """

    def __init__(
        self,
        id: Optional[str] = None,
        name: str = "",
        commander_text: str = "",
        mainboard_text: str = "",
        sideboard_text: str = "",
        created_at: Optional[str] = None,
        analysis_id: Optional[str] = None,
        sleeve_id: Optional[str] = None,
        author: Optional[str] = None,
        color_identity: Optional[list[str]] = None,
        commanders: Optional[list[str]] = None,
        is_cube: bool = False,
        archetypes: Optional[list[str]] = None,
        favorite_cards: Optional[list[str]] = None,
        validation_result: Optional[dict[str, Any]] = None,
        unmodeled_coverage: Optional[dict[str, Any]] = None,
        unmodeled_coverage_version: Optional[str] = None,
    ) -> None:
        self.id = id or str(uuid.uuid4())
        self.name = name
        self.commander_text = commander_text
        self.mainboard_text = mainboard_text
        self.sideboard_text = sideboard_text
        self.created_at = created_at or datetime.now(timezone.utc).isoformat()
        self.analysis_id = analysis_id
        self.sleeve_id = sleeve_id
        self.author = author
        self.color_identity = color_identity
        self.commanders = commanders
        self.is_cube = is_cube
        self.archetypes = archetypes
        self.favorite_cards = favorite_cards
        self.validation_result = validation_result
        self.unmodeled_coverage = unmodeled_coverage
        self.unmodeled_coverage_version = unmodeled_coverage_version

    def to_dict(self) -> dict[str, Any]:
        """Serialize this deck to a JSON-compatible dict (camelCase, like ParsedDeck)."""
        return {
            "id": self.id,
            "name": self.name,
            "commanderText": self.commander_text,
            "mainboardText": self.mainboard_text,
            "sideboardText": self.sideboard_text,
            "createdAt": self.created_at,
            "analysisId": self.analysis_id,
            "sleeveId": self.sleeve_id,
            "author": self.author,
            "colorIdentity": self.color_identity,
            "commanders": self.commanders,
            "isCube": self.is_cube,
            "archetypes": self.archetypes,
            "favoriteCards": self.favorite_cards,
            "validationResult": self.validation_result,
            "unmodeledCoverage": self.unmodeled_coverage,
            "unmodeledCoverageVersion": self.unmodeled_coverage_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Deck":
        """Deserialize a Deck from a dict produced by to_dict()."""
        return cls(
            id=data.get("id"),
            name=data.get("name", ""),
            commander_text=data.get("commanderText", ""),
            mainboard_text=data.get("mainboardText", ""),
            sideboard_text=data.get("sideboardText", ""),
            created_at=data.get("createdAt"),
            analysis_id=data.get("analysisId"),
            sleeve_id=data.get("sleeveId"),
            author=data.get("author"),
            color_identity=data.get("colorIdentity"),
            commanders=data.get("commanders"),
            is_cube=data.get("isCube", False),
            archetypes=data.get("archetypes"),
            favorite_cards=data.get("favoriteCards"),
            validation_result=data.get("validationResult"),
            unmodeled_coverage=data.get("unmodeledCoverage"),
            unmodeled_coverage_version=data.get("unmodeledCoverageVersion"),
        )

    def __repr__(self) -> str:
        return f"Deck(id={self.id!r}, name={self.name!r}, created_at={self.created_at!r})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Deck):
            return NotImplemented
        return self.to_dict() == other.to_dict()
