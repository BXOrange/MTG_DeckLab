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

`TokenArtLibrary` (below) is a second, much larger, art-*only* dataset
(`data/token_art.json`, built by `scripts/build_token_art_library.py`) for
every *vanilla* token — one an effect synthesizes inline from a clause
("create a 1/1 white Soldier creature token") rather than looking up by
name, so it has no ability and would otherwise get no art at all. See its
own docstring for why it exists separately from the curated catalogue above.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, Union

from mtg_analyzer.models.cards.card import Card

#: The committed token catalogue that ships with the package.
DEFAULT_TOKENS_PATH = Path(__file__).resolve().parent.parent / "data" / "tokens.json"

#: The committed *art-only* token library — see `TokenArtLibrary`.
DEFAULT_TOKEN_ART_PATH = Path(__file__).resolve().parent.parent / "data" / "token_art.json"


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


class TokenArtLibrary:
    """Art-only lookup over every *vanilla* token Scryfall has ever printed.

    Built by `scripts/build_token_art_library.py` from Scryfall's own token
    sheets into `data/token_art.json`: one representative printing per
    distinct (name, power, toughness, colors) combination. This is
    deliberately a separate, much larger dataset from `data/tokens.json`
    (`TokenDatabase`, curated by hand): most tokens an effect creates have no
    ability of their own — "create a 1/1 white Soldier" — so `TokenDatabase`
    would never carry one, but a player still expects the token's actual
    printed art instead of a text tile.

    The (name, power, toughness, colors) key is the whole point of a
    *library* rather than a flat name → art map: Magic reprints the same
    token name at different stat lines across sets (a "Shapeshifter" token
    exists as a 1/1, a 2/2, and others, in different colors) — matching by
    name alone would show one variant's art on every other variant. Matching
    ignores ``subtypes``: for a vanilla token, the name *is* its subtypes
    joined (`synthesize_token_card`'s own ``token_name`` default), so it adds
    no discriminating power the (name, power, toughness, colors) key doesn't
    already have.

    This is purely cosmetic — a miss just means the caller keeps building an
    imageless token exactly as before (the pre-existing behaviour), never a
    hard failure.
    """

    def __init__(self, path: Union[str, Path] = DEFAULT_TOKEN_ART_PATH) -> None:
        self._by_key: dict[tuple, dict] = {}
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except FileNotFoundError:
            raw = []
        for entry in raw:
            key = self._key(entry["name"], entry["power"], entry["toughness"], entry["colors"])
            # First entry wins on a key collision — the build script already
            # de-duplicates by this exact key, so a collision here would only
            # mean two differently-cased names normalizing to the same key.
            self._by_key.setdefault(key, entry)

    @staticmethod
    def _key(
        name: str, power: Optional[int], toughness: Optional[int], colors: Optional[list[str]]
    ) -> tuple[str, Optional[int], Optional[int], frozenset[str]]:
        return (name.strip().casefold(), power, toughness, frozenset(colors or []))

    def find(
        self,
        name: Optional[str],
        power: Optional[int],
        toughness: Optional[int],
        colors: Optional[list[str]],
    ) -> Optional[dict]:
        """The library entry matching this exact (name, P/T, colors), if any."""
        if not name:
            return None
        return self._by_key.get(self._key(name, power, toughness, colors))


#: Lazily-built process-wide default library (reads the JSON once).
_default_art_library: Optional[TokenArtLibrary] = None


def default_token_art_library() -> TokenArtLibrary:
    """The shared `TokenArtLibrary` over the repo's committed art dataset."""
    global _default_art_library
    if _default_art_library is None:
        _default_art_library = TokenArtLibrary()
    return _default_art_library


def jace_token_card() -> Card:
    """RULE 701.71: nonlegendary blue Jace with zero starting loyalty."""
    art = default_token_art_library().find("Jace", None, None, ["U"])
    return Card(
        id=art["id"] if art else "token:empower-jace",
        name="Jace", type_line="Token Planeswalker — Jace",
        color_identity={"U"}, loyalty=0,
        oracle_text="−1: Surveil 1.\n−3: Draw a card.",
        image_uri_small=art["image_uri_small"] if art else "",
        image_uri_normal=art["image_uri_normal"] if art else "",
        image_uri_large=art["image_uri_large"] if art else "",
        image_uri_png=art["image_uri_png"] if art else "",
    )


def synthesize_token_card(
    name: str,
    power: Optional[int] = None,
    toughness: Optional[int] = None,
    colors: Optional[list[str]] = None,
    subtypes: Optional[list[str]] = None,
    keywords: Optional[list[str]] = None,
    oracle_text: str = "",
    legendary: bool = False,
    is_artifact: bool = False,
) -> Card:
    """Build a `Card` *definition* for a token an effect creates on the fly.

    Used when a "create a 1/1 white Soldier creature token" clause has no
    matching entry in the curated catalogue: the token's characteristics come
    straight from the clause. The ``type_line`` starts with "Token" so
    `Card.is_token` is True and the parser/binder treat any granted keywords
    exactly like a real card's. A token with power/toughness is a creature; one
    without is a generic artifact (e.g. Treasure/Clue when not catalogued).

    ``is_artifact=True`` (Construct/Thopter/Servo-shaped "colorless Construct
    **artifact** creature token") adds the Artifact card type *alongside*
    Creature rather than instead of it — real Magic prints plenty of
    artifact creature tokens, and "sacrifice an artifact"/an artifact-count
    anthem/RULE 704.5f's own zero-toughness check all need `Card.is_artifact`
    true for one of these, not just `Card.is_creature`.

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
    if is_creature:
        kind = "Artifact Creature" if is_artifact else "Creature"
    else:
        kind = "Artifact"
    type_line = f"Token{' Legendary' if legendary else ''} {kind}"
    if subtypes:
        type_line += " — " + " ".join(s.capitalize() for s in subtypes)
    token_name = name or (subtypes[0] if subtypes else "Token")
    # Cosmetic only: a hit gives this ad hoc token its real printed art (and,
    # so a same-named different-stats variant can't collide on it, that
    # printing's own Scryfall id in place of the generic `token:name:p/t`
    # placeholder — see `TokenArtLibrary`). A miss changes nothing; the
    # caller gets exactly the imageless token it always did.
    art = default_token_art_library().find(token_name, power, toughness, colors)
    return Card(
        id=art["id"] if art else f"token:{token_name}:{power}/{toughness}",
        name=token_name,
        type_line=type_line,
        is_creature=is_creature,
        is_legendary=legendary,
        power=power,
        toughness=toughness,
        color_identity=set(colors or []),
        keywords=list(keywords or []),
        oracle_text=oracle_text,
        image_uri_small=art["image_uri_small"] if art else "",
        image_uri_normal=art["image_uri_normal"] if art else "",
        image_uri_large=art["image_uri_large"] if art else "",
        image_uri_png=art["image_uri_png"] if art else "",
    )
