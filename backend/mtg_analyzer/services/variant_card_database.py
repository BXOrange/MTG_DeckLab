"""Read-only catalogue of the casual-variant card types (RULE 9), committed
to the repo: **planes** (RULE 901 Planechase), **schemes** (RULE 904
Archenemy) and **Vanguard avatars** (RULE 902).

Same reasoning as `services/dungeon_database.py` and
`services/token_database.py`: none of these is ever in a decklist or looked
up by name from a request. They live *outside the game* in their own
supplemental deck, and `scripts/import_bulk.py` deliberately drops their
Scryfall layouts (`planar`/`scheme`/`vanguard`) from the app card cache so
the oracle-parser coverage denominator stays "cards a player can cast". A
committed catalogue is therefore the only place they can come from.

An entry is turned into a `Card` by `card_for`, which is all the engine
needs: a plane/scheme/avatar is an ordinary `GameObject` in the command
zone whose abilities bind through the same `effect_binder` path a permanent's
do.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional, Union

from mtg_analyzer.models.card import Card

#: The committed variant-card catalogue that ships with the package.
DEFAULT_VARIANT_CARDS_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "variant_cards.json"
)

#: The Scryfall layouts this catalogue holds, and the kind name the engine
#: uses for each.
LAYOUT_KINDS: dict[str, str] = {
    "planar": "plane",      # RULE 901: planes (and phenomena, same layout)
    "scheme": "scheme",     # RULE 904
    "vanguard": "vanguard",  # RULE 902
}


class VariantCardDatabase:
    """In-memory lookup over the repo's plane/scheme/avatar definitions."""

    def __init__(
        self, path: Union[str, Path] = DEFAULT_VARIANT_CARDS_PATH
    ) -> None:
        self._path = Path(path)
        self._by_kind: dict[str, list[dict[str, Any]]] = {kind: [] for kind in LAYOUT_KINDS.values()}
        self._by_name: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        raw = json.loads(self._path.read_text(encoding="utf-8"))
        for entry in raw:
            kind = LAYOUT_KINDS.get(entry.get("layout") or "")
            if kind is None:
                raise ValueError(
                    f"{entry.get('name')!r} in {self._path.name} has unknown layout "
                    f"{entry.get('layout')!r}"
                )
            self._by_kind[kind].append(entry)
            self._by_name[(entry.get("name") or "").casefold()] = entry

    def of_kind(self, kind: str) -> list[dict[str, Any]]:
        """Every entry of one kind (``"plane"``/``"scheme"``/``"vanguard"``)."""
        return list(self._by_kind.get(kind, []))

    def get(self, name: str) -> Optional[dict[str, Any]]:
        return self._by_name.get(name.strip().casefold())

    def __len__(self) -> int:
        return sum(len(v) for v in self._by_kind.values())


def card_for(entry: dict[str, Any]) -> Card:
    """One catalogue entry → the `Card` the engine plays with.

    A plane/scheme/avatar has no mana cost, no power/toughness and no colour
    — its type line and its rules text are the whole card, which is exactly
    what the ability binder reads."""
    return Card(
        id=entry.get("id") or entry.get("name") or "",
        name=entry.get("name") or "",
        type_line=entry.get("type_line") or "",
        oracle_text=entry.get("oracle_text") or "",
        set_code=entry.get("set_code") or "",
        layout=entry.get("layout") or "",
        image_uri_small=entry.get("image_uri_small") or "",
        image_uri_normal=entry.get("image_uri_normal") or "",
    )


#: Lazily-built process-wide default catalogue (reads the JSON once).
_default_db: Optional[VariantCardDatabase] = None


def default_variant_card_database() -> VariantCardDatabase:
    """The shared `VariantCardDatabase` over the repo's committed catalogue."""
    global _default_db
    if _default_db is None:
        _default_db = VariantCardDatabase()
    return _default_db
