"""Read-only catalogue of dungeon cards (RULE 309), committed to the repo.

Same "three-tier durability" reasoning as `services/token_database.py`: a
dungeon card is **never** in a decklist and never looked up by name from a
request — RULE 309.2 says dungeon cards begin *outside the game* and are
brought in only by the venture keyword action — so the small, fixed set of
them ships with the source rather than living in the disposable, lazily
populated card cache. Two of the five aren't even in that cache: the bulk
importer deliberately drops the `double_faced_token` layout Undercity is
printed under (`scripts/import_bulk.py`'s `_SKIP_LAYOUTS`), and doing so
keeps the parser's coverage denominator honest — a dungeon is not a card a
player can cast.

The JSON carries the printed card text verbatim; `game/dungeons.py` turns
each card's room lines into the `Dungeon`/`DungeonRoom` graph the engine
walks.

The catalogue holds the four dungeons whose printed text actually encodes
that graph — the three *Adventures in the Forgotten Realms* dungeons plus
Undercity (RULE 726.2's own dungeon). Deliberately **not** included:
Baldur's Gate Wilderness, whose Oracle text lists rooms with no "(Leads
to: …)" arrows at all, so every room would read as a bottommost one (RULE
309.5b) and a single venture would complete the whole dungeon. A dungeon
whose graph can't be read is worse than an absent one; add it here if the
Oracle text ever gains its arrows.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional, Union

#: The committed dungeon catalogue that ships with the package.
DEFAULT_DUNGEONS_PATH = Path(__file__).resolve().parent.parent / "data" / "dungeons.json"


class DungeonDatabase:
    """In-memory lookup over the repo's dungeon definitions (loaded once)."""

    def __init__(self, dungeons_path: Union[str, Path] = DEFAULT_DUNGEONS_PATH) -> None:
        self._path = Path(dungeons_path)
        self._entries: list[dict[str, Any]] = []
        self._by_name: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        raw = json.loads(self._path.read_text(encoding="utf-8"))
        for entry in raw:
            type_line = (entry.get("type_line") or "")
            if not type_line.startswith("Dungeon"):
                # The catalogue must contain only dungeons — anything else is
                # a data error, not something to silently serve (the same
                # guard `TokenDatabase` applies to its own file).
                raise ValueError(
                    f"{entry.get('name')!r} in {self._path.name} is not a dungeon "
                    f"(type_line {type_line!r})"
                )
            self._entries.append(entry)
            self._by_name[(entry.get("name") or "").casefold()] = entry

    def get(self, name: str) -> Optional[dict[str, Any]]:
        return self._by_name.get(name.strip().casefold())

    def all_dungeons(self) -> list[dict[str, Any]]:
        return list(self._entries)

    def __len__(self) -> int:
        return len(self._entries)


#: Lazily-built process-wide default catalogue (reads the JSON once).
_default_db: Optional[DungeonDatabase] = None


def default_dungeon_database() -> DungeonDatabase:
    """The shared `DungeonDatabase` over the repo's committed catalogue."""
    global _default_db
    if _default_db is None:
        _default_db = DungeonDatabase()
    return _default_db
