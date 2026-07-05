"""Card model representing a single Magic: The Gathering card.

Reference: /docs/06_CARD_GRAPHICS_AND_LAZY_LOADING.md (PART 1)
"""

from __future__ import annotations

from typing import Any, Optional

#: Colors that may legally appear in a card's color identity.
VALID_COLORS: frozenset[str] = frozenset({"W", "U", "B", "R", "G"})

#: Default mana cost used when none is supplied.
_DEFAULT_MANA_COST: dict[str, int] = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0}


class Card:
    """A single Magic: The Gathering card and its game-relevant attributes.

    Attributes:
        id: Scryfall UUID identifying this card.
        name: The card's name.
        mana_cost: Mapping of mana symbol to amount required to cast the
            card, e.g. {"W": 1, "U": 0, "B": 0, "R": 1, "G": 0, "C": 0}.
            This is a lossy per-color pip tally kept for the frontend's
            pip displays; it can't distinguish hybrid/Phyrexian pips or
            represent generic cost. For anything that pays a cost, prefer
            `mana_cost_string` + `models.mana_cost.ManaCost`.
        mana_cost_string: The card's raw Scryfall mana cost, e.g.
            "{2}{W}{U/B}". Preserves hybrid/Phyrexian/generic faithfully
            so the game engine can compute the real ways to pay a cost
            (see models/mana_cost.py); empty for lands and most tokens.
        converted_mana_cost: Total converted mana cost (mana value).
        color_identity: Colors ("W", "U", "B", "R", "G") in the card's
            color identity.
        type_line: Full type line, e.g. "Creature — Goblin Wizard".
        is_creature: Whether the card is a creature.
        is_instant: Whether the card is an instant.
        is_sorcery: Whether the card is a sorcery.
        is_land: Whether the card is a land.
        power: Creature power, or None if the card is not a creature.
        toughness: Creature toughness, or None if the card is not a creature.
        oracle_text: The card's rules text.
        keywords: Machine-readable keyword abilities parsed out of the
            oracle text (e.g. ["Flying", "Trample"]), as reported by
            Scryfall. This is a lookup table for the Phase 2 effect
            system (docs/07_GAME_LOOP_EFFECT_SYSTEM.md); it does not
            itself execute anything.
        image_uri_small: URL of the small Scryfall image.
        image_uri_normal: URL of the normal Scryfall image.
        image_uri_large: URL of the large Scryfall image.
        image_uri_png: URL of the print-quality Scryfall image.
        set_code: The set this printing is from, e.g. "ltr".
        rarity: The printing's rarity, e.g. "common", "mythic".
        is_legendary: Whether the card has the legendary supertype.
        has_partner: Whether the card has "Partner" or "Partner with X".
        partner_with: The named partner card if this card has
            "Partner with X", otherwise None.
    """

    def __init__(
        self,
        id: str,
        name: str,
        type_line: str,
        mana_cost: Optional[dict[str, int]] = None,
        mana_cost_string: str = "",
        converted_mana_cost: int = 0,
        color_identity: Optional[set[str]] = None,
        is_creature: bool = False,
        is_instant: bool = False,
        is_sorcery: bool = False,
        is_land: bool = False,
        power: Optional[int] = None,
        toughness: Optional[int] = None,
        oracle_text: str = "",
        keywords: Optional[list[str]] = None,
        image_uri_small: str = "",
        image_uri_normal: str = "",
        image_uri_large: str = "",
        image_uri_png: str = "",
        set_code: str = "",
        rarity: str = "",
        is_legendary: bool = False,
        has_partner: bool = False,
        partner_with: Optional[str] = None,
    ) -> None:
        """Construct a Card, validating attributes per the data model spec.

        Raises:
            ValueError: If name or type_line is empty, if power/toughness
                are set on a non-creature, or if color_identity contains a
                symbol outside W/U/B/R/G.
        """
        if not name or not name.strip():
            raise ValueError("name must be non-empty")
        if not type_line or not type_line.strip():
            raise ValueError("type_line must be non-empty")
        if not is_creature and (power is not None or toughness is not None):
            raise ValueError("power/toughness may only be set on creatures")

        if color_identity is None:
            color_identity = set()
        invalid_colors = set(color_identity) - VALID_COLORS
        if invalid_colors:
            raise ValueError(
                f"invalid color_identity symbols: {sorted(invalid_colors)}"
            )

        self.id = id
        self.name = name
        self.mana_cost = dict(mana_cost) if mana_cost is not None else dict(_DEFAULT_MANA_COST)
        self.mana_cost_string = mana_cost_string
        self.converted_mana_cost = converted_mana_cost
        self.color_identity = set(color_identity)
        self.type_line = type_line
        self.is_creature = is_creature
        self.is_instant = is_instant
        self.is_sorcery = is_sorcery
        self.is_land = is_land
        self.power = power
        self.toughness = toughness
        self.oracle_text = oracle_text
        self.keywords = list(keywords) if keywords is not None else []
        self.image_uri_small = image_uri_small
        self.image_uri_normal = image_uri_normal
        self.image_uri_large = image_uri_large
        self.image_uri_png = image_uri_png
        self.set_code = set_code
        self.rarity = rarity
        self.is_legendary = is_legendary
        self.has_partner = has_partner
        self.partner_with = partner_with

    @property
    def has_mana_cost_data(self) -> bool:
        """Whether `mana_cost_string` reflects a real Scryfall lookup.

        Scryfall gives every non-land an explicit cost string (even a
        genuinely free one is `"{0}"`, not blank) — so a non-land card with
        a blank `mana_cost_string` means this row predates that field
        (`backend/Done_Backend.md` "Mana cost model"), not that the card
        is actually free. `ManaCost.from_card` can still *price* such a row
        from the legacy pip tally, just without hybrid/Phyrexian fidelity;
        `LazyCardLoader` uses this flag to refetch it instead of serving
        the stale copy forever.
        """
        return bool(self.mana_cost_string) or self.is_land

    def to_dict(self) -> dict[str, Any]:
        """Serialize this card to a JSON-compatible dict."""
        return {
            "id": self.id,
            "name": self.name,
            "mana_cost": dict(self.mana_cost),
            "mana_cost_string": self.mana_cost_string,
            "converted_mana_cost": self.converted_mana_cost,
            "color_identity": sorted(self.color_identity),
            "type_line": self.type_line,
            "is_creature": self.is_creature,
            "is_instant": self.is_instant,
            "is_sorcery": self.is_sorcery,
            "is_land": self.is_land,
            "power": self.power,
            "toughness": self.toughness,
            "oracle_text": self.oracle_text,
            "keywords": list(self.keywords),
            "image_uri_small": self.image_uri_small,
            "image_uri_normal": self.image_uri_normal,
            "image_uri_large": self.image_uri_large,
            "image_uri_png": self.image_uri_png,
            "set_code": self.set_code,
            "rarity": self.rarity,
            "is_legendary": self.is_legendary,
            "has_partner": self.has_partner,
            "partner_with": self.partner_with,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Card":
        """Deserialize a Card from a dict produced by to_dict()."""
        return cls(
            id=data["id"],
            name=data["name"],
            type_line=data["type_line"],
            mana_cost=data.get("mana_cost"),
            mana_cost_string=data.get("mana_cost_string", ""),
            converted_mana_cost=data.get("converted_mana_cost", 0),
            color_identity=set(data.get("color_identity") or []),
            is_creature=data.get("is_creature", False),
            is_instant=data.get("is_instant", False),
            is_sorcery=data.get("is_sorcery", False),
            is_land=data.get("is_land", False),
            power=data.get("power"),
            toughness=data.get("toughness"),
            oracle_text=data.get("oracle_text", ""),
            keywords=data.get("keywords"),
            image_uri_small=data.get("image_uri_small", ""),
            image_uri_normal=data.get("image_uri_normal", ""),
            image_uri_large=data.get("image_uri_large", ""),
            image_uri_png=data.get("image_uri_png", ""),
            set_code=data.get("set_code", ""),
            rarity=data.get("rarity", ""),
            is_legendary=data.get("is_legendary", False),
            has_partner=data.get("has_partner", False),
            partner_with=data.get("partner_with"),
        )

    def __deepcopy__(self, memo: dict) -> "Card":
        """Return self: a Card is an immutable printed definition.

        Game state (mtg_analyzer/models/game_state.py) is deep-copied for
        undo/rewind; the cards a `GameObject` points at are never mutated
        during play, so sharing them keeps clones cheap and avoids
        duplicating the whole card pool per snapshot.
        """
        return self

    def __repr__(self) -> str:
        return (
            f"Card(id={self.id!r}, name={self.name!r}, type_line={self.type_line!r}, "
            f"mana_cost={self.mana_cost!r}, power={self.power!r}, toughness={self.toughness!r})"
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Card):
            return NotImplemented
        return self.to_dict() == other.to_dict()
