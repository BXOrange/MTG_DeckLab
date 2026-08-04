"""Read-only catalogue of token definitions, committed to the repository.

Reference: docs/concepts/09_ORACLE_EFFECT_PARSER.md (the three-tier durability
model — a curated catalogue lives in the repo, in contrast with the
volatile, lazily-populated card cache).

Tokens (Treasure, Clue, Food, creature tokens, …) are never named in a
decklist and never fetched from Scryfall at request time — they are
*created by effects* during play. Their printed definitions are therefore
a small, curated set that ships **with the source**, unlike
`CardDatabase` (a disposable on-disk cache re-fetchable from Scryfall).
This service loads that set from ``mtg_analyzer/data/tokens.json``.

A token definition reuses the `Card` model (its `type_line` starts with
"Token", so `Card.is_token` is True), which lets the oracle-text → effect
parser and binder treat a Treasure's "{T}, Sacrifice this token: Add one
mana of any color." exactly like any real card's ability.

Only the JSON (ids, oracle text, types, image *URLs*) lives in the repo;
the image *bytes* are still lazy-loaded on first use through the same
`ImageCache`, which is keyed by the Scryfall id every token carries — so
token art costs nothing until something actually renders it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, Union

from mtg_analyzer.models.card import Card

#: The committed token catalogue that ships with the package.
DEFAULT_TOKENS_PATH = Path(__file__).resolve().parent.parent / "data" / "tokens.json"


class TokenDatabase:
    """In-memory lookup over the repo's token definitions (loaded once)."""

    def __init__(self, tokens_path: Union[str, Path] = DEFAULT_TOKENS_PATH) -> None:
        self._path = Path(tokens_path)
        self._by_id: dict[str, Card] = {}
        self._by_name: dict[str, Card] = {}
        self._load()

    def _load(self) -> None:
        raw = json.loads(self._path.read_text(encoding="utf-8"))
        for entry in raw:
            card = Card.from_dict(entry)
            if not card.is_token:
                # The catalogue must contain only tokens — a real card here
                # is a data error, not something to silently serve.
                raise ValueError(
                    f"{card.name!r} in {self._path.name} is not a token "
                    f"(type_line {card.type_line!r} does not start with 'Token')"
                )
            self._by_id[card.id] = card
            self._by_name[card.name.casefold()] = card

    def get_token(self, name: str) -> Optional[Card]:
        """Look up a token definition by exact name, case-insensitively."""
        return self._by_name.get(name.strip().casefold())

    def get_token_by_id(self, token_id: str) -> Optional[Card]:
        """Look up a token definition by its Scryfall id."""
        return self._by_id.get(token_id)

    def all_tokens(self) -> list[Card]:
        """Every token definition in the catalogue."""
        return list(self._by_id.values())

    def __len__(self) -> int:
        return len(self._by_id)


#: Lazily-built process-wide default catalogue (reads the JSON once).
_default_db: Optional[TokenDatabase] = None


def default_token_database() -> TokenDatabase:
    """The shared `TokenDatabase` over the repo's committed token catalogue."""
    global _default_db
    if _default_db is None:
        _default_db = TokenDatabase()
    return _default_db


def synthesize_token_card(
    name: str,
    power: Optional[int] = None,
    toughness: Optional[int] = None,
    colors: Optional[list[str]] = None,
    subtypes: Optional[list[str]] = None,
    keywords: Optional[list[str]] = None,
    oracle_text: str = "",
    legendary: bool = False,
) -> Card:
    """Build a `Card` *definition* for a token an effect creates on the fly.

    Used when a "create a 1/1 white Soldier creature token" clause has no
    matching entry in the curated catalogue: the token's characteristics come
    straight from the clause. The ``type_line`` starts with "Token" so
    `Card.is_token` is True and the parser/binder treat any granted keywords
    exactly like a real card's. A token with power/toughness is a creature; one
    without is a generic artifact (e.g. Treasure/Clue when not catalogued).

    ``legendary`` (PAR-13, "Create The Atropal, a legendary 4/4 black God
    Horror creature token with deathtouch.") sets `Card.is_legendary`
    directly — this builder makes a `Card` straight from parts rather than
    through `Card.from_scryfall_data`'s own type-line-derived reading, so it
    has to be passed explicitly rather than inferred from ``type_line``
    after the fact. "Token" stays the type line's first word regardless
    (`Card.is_token`'s own contract), with "Legendary" folded in right
    after it, matching where the supertype actually sits.
    """
    is_creature = power is not None and toughness is not None
    subtypes = subtypes or ([name] if (name and is_creature) else [])
    kind = "Creature" if is_creature else "Artifact"
    type_line = f"Token{' Legendary' if legendary else ''} {kind}"
    if subtypes:
        type_line += " — " + " ".join(s.capitalize() for s in subtypes)
    token_name = name or (subtypes[0] if subtypes else "Token")
    return Card(
        id=f"token:{token_name}:{power}/{toughness}",
        name=token_name,
        type_line=type_line,
        is_creature=is_creature,
        is_legendary=legendary,
        power=power,
        toughness=toughness,
        color_identity=set(colors or []),
        keywords=list(keywords or []),
        oracle_text=oracle_text,
    )
