"""Deck model: a saved decklist, identified by a UUID rather than its name.

Reference: docs/04_SERVER_CLIENT_ARCHITECTURE.md (PART 4, REST
endpoints), backend/Done_Backend.md "Deck persistence".
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

    `analysis_id` is a reserved hook for a future LLM deck analysis
    feature (UC2, backend/ToDo_Backend.md "LLM Deck Analysis"): nothing
    populates or reads it yet, but the field exists now so that feature
    can link a deck to its analysis without a storage migration later.
    Treat its exact shape (a single id vs. something richer) as
    provisional until that feature is actually built.
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
    ) -> None:
        self.id = id or str(uuid.uuid4())
        self.name = name
        self.commander_text = commander_text
        self.mainboard_text = mainboard_text
        self.sideboard_text = sideboard_text
        self.created_at = created_at or datetime.now(timezone.utc).isoformat()
        self.analysis_id = analysis_id

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
        )

    def __repr__(self) -> str:
        return f"Deck(id={self.id!r}, name={self.name!r}, created_at={self.created_at!r})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Deck):
            return NotImplemented
        return self.to_dict() == other.to_dict()
