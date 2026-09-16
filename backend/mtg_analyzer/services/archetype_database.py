"""Read-only catalogue of EDH deck archetypes (themes/strategies), committed
to the repo.

Same "committed reference data, not the disposable card cache" reasoning as
`services/dungeon_database.py`/`services/token_database.py`: an archetype
definition is hand-authored MTG-community knowledge (EDHREC-style
categories — Aristocrats, Stax, Voltron, ...), not something derived from a
Scryfall lookup, so it ships as JSON in `data/` rather than living behind
`config.DATA_DIR` (reserved for disposable/user runtime data).

Each entry (see `data/archetypes.json`):

    {
      "id": "aristocrats",              # stable id, referenced by Deck.archetypes
      "label": "Aristocrats",           # display name (archetype names stay
                                         # English, same convention as MTG
                                         # keywords elsewhere in this app)
      "description": "...",             # German, shown as UI hint text
      "signal_cards": {
        "core": ["Blood Artist", ...],      # iconic staples/build-arounds
        "support": ["Viscera Seer", ...]    # secondary staples
      },
      "synergy_patterns": ["sacrifice a creature", ...],  # case-insensitive
                                                           # regexes matched
                                                           # against oracle text
      "win_condition_cards": ["Blood Artist", ...],  # the "plan cards" that
                                                       # typically close the
                                                       # game for this archetype
      "score_threshold": 24             # per-archetype scoring ceiling,
                                         # see services/archetype_analysis.py
    }

Deliberately **not** included: per-creature-type ("typal"/tribal) entries —
those are detected dynamically from a deck's own creature-type distribution
(`services/archetype_analysis.py`'s `detect_typal_signals`) rather than
enumerated by hand, since EDHREC alone lists dozens of tribes and a fixed
list would go stale as new tribal support prints.

This file is meant to be grown over time by hand, the same authoring model
`game/card_catalogue` uses — it ships with a first curated pass and is
extended in later sessions, not regenerated from an external source at
runtime (this app stays offline-safe; no live EDHREC/internet calls).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional, Union

#: The committed archetype catalogue that ships with the package.
DEFAULT_ARCHETYPES_PATH = Path(__file__).resolve().parent.parent / "data" / "archetypes.json"

#: Every field an entry must carry — a malformed/incomplete entry is a data
#: error in the catalogue, not something to silently serve half of.
_REQUIRED_FIELDS = frozenset(
    {"id", "label", "description", "signal_cards", "synergy_patterns", "win_condition_cards", "score_threshold"}
)


class ArchetypeDatabase:
    """In-memory lookup over the repo's archetype catalogue (loaded once)."""

    def __init__(self, archetypes_path: Union[str, Path] = DEFAULT_ARCHETYPES_PATH) -> None:
        self._path = Path(archetypes_path)
        self._entries: list[dict[str, Any]] = []
        self._by_id: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        raw = json.loads(self._path.read_text(encoding="utf-8"))
        for entry in raw:
            missing = _REQUIRED_FIELDS - entry.keys()
            if missing:
                raise ValueError(
                    f"{entry.get('id')!r} in {self._path.name} is missing field(s) {sorted(missing)}"
                )
            entry_id = entry["id"]
            if entry_id in self._by_id:
                raise ValueError(f"duplicate archetype id {entry_id!r} in {self._path.name}")
            self._entries.append(entry)
            self._by_id[entry_id] = entry

    def get(self, archetype_id: str) -> Optional[dict[str, Any]]:
        return self._by_id.get(archetype_id)

    def all_archetypes(self) -> list[dict[str, Any]]:
        return list(self._entries)

    def __len__(self) -> int:
        return len(self._entries)


#: Lazily-built process-wide default catalogue (reads the JSON once).
_default_db: Optional[ArchetypeDatabase] = None


def default_archetype_database() -> ArchetypeDatabase:
    """The shared `ArchetypeDatabase` over the repo's committed catalogue."""
    global _default_db
    if _default_db is None:
        _default_db = ArchetypeDatabase()
    return _default_db
