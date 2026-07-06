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
        layout: Scryfall's printed layout, e.g. "normal", "transform",
            "modal_dfc", "flip", "split", "adventure", "meld". Empty for
            rows cached before this field existed. This is what decides
            *how* a second face is reached — see `is_modal_dfc` (the back
            is a separately-castable card) vs. `is_transforming` (the
            back is only reached by a transform effect on the
            battlefield) vs. single-image layouts like "flip"/"split".
        back_name: Name of the back face, or "" if the card has no
            distinct second face (or the row predates DFC support).
        back_type_line: Type line of the back face.
        back_oracle_text: Rules text of the back face.
        back_mana_cost_string: Raw Scryfall mana cost of the back face
            (empty for a transform back, which is never cast for a cost).
        back_power/back_toughness: Back face's power/toughness if it is a
            creature, else None.
        back_image_uri_small/normal/large/png: Scryfall image URLs for the
            back face. Only populated for layouts that print two separate
            face images (transform, modal_dfc, double_faced_token); a
            "flip"/"split" card shows a single shared image and leaves
            these empty. See `has_back_face`.
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
        layout: str = "",
        back_name: str = "",
        back_type_line: str = "",
        back_oracle_text: str = "",
        back_mana_cost_string: str = "",
        back_power: Optional[int] = None,
        back_toughness: Optional[int] = None,
        back_image_uri_small: str = "",
        back_image_uri_normal: str = "",
        back_image_uri_large: str = "",
        back_image_uri_png: str = "",
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
        self.layout = layout
        self.back_name = back_name
        self.back_type_line = back_type_line
        self.back_oracle_text = back_oracle_text
        self.back_mana_cost_string = back_mana_cost_string
        self.back_power = back_power
        self.back_toughness = back_toughness
        self.back_image_uri_small = back_image_uri_small
        self.back_image_uri_normal = back_image_uri_normal
        self.back_image_uri_large = back_image_uri_large
        self.back_image_uri_png = back_image_uri_png

    @property
    def has_back_face(self) -> bool:
        """Whether this card has a distinct, separately-imaged back face.

        True only for layouts that print two face images — a transform
        card (Delver), a modal DFC (Valki // Tibalt), a double-faced
        token. A "flip" (Kamigawa) or "split"/"adventure" card has two
        *faces* in Scryfall's data but one shared image, so it reports
        False: there is nothing to flip *to* image-wise. Derived from
        whether a back image URL was captured rather than from `layout`
        alone, so a row cached before `layout` existed still answers
        correctly if it happens to carry back-image data.
        """
        return bool(self.back_image_uri_normal or self.back_image_uri_small)

    @property
    def is_modal_dfc(self) -> bool:
        """Whether the back face is a *separately castable* card (RULE 712).

        A modal DFC (e.g. "Valki, God of Lies // Tibalt, Cosmic
        Impostor") lets the player choose which face to play from hand;
        the two faces are independent cards sharing one physical object.
        Contrast `is_transforming`, where the back is never chosen from
        hand.
        """
        return self.layout == "modal_dfc"

    @property
    def is_transforming(self) -> bool:
        """Whether the back face is reached only by transforming in play.

        A transform DFC (Delver of Secrets, werewolves, flip
        planeswalkers) always enters as its front face; the back is a
        battlefield-only state reached by a transform effect, never cast
        from hand. Contrast `is_modal_dfc`.
        """
        return self.layout == "transform"

    @property
    def is_token(self) -> bool:
        """Whether this definition is a token rather than a real card.

        Derived from the type line rather than stored: every Scryfall token
        object's ``type_line`` begins with "Token" (e.g. "Token Artifact —
        Treasure", "Token Creature — Soldier"), so token-ness needs no extra
        field on the serialized row and no cache-schema change. Tokens reuse
        this `Card` model as their printed *definition* (see
        services/token_database.py) so the oracle-text → effect parser and
        binder treat a token's abilities exactly like a real card's; the
        rules-critical difference (a token ceases to exist when it leaves the
        battlefield, RULE 704.5d) belongs on the in-play `GameObject`, not
        here.
        """
        return self.type_line.strip().startswith("Token")

    @property
    def has_image_data(self) -> bool:
        """Whether this row carries a usable front-face image URL.

        Rows cached by an older build (notably double-faced cards, whose
        image URLs live under `card_faces` and were dropped before DFC
        support) can have blank image URIs while still having a mana
        cost — so `has_mana_cost_data` alone would keep serving them
        image-less forever. `LazyCardLoader` pairs this with that flag to
        decide a row needs refetching. Tokens legitimately may lack an
        image, so they're exempt.
        """
        return bool(self.image_uri_normal or self.image_uri_small) or self.is_token

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
            "layout": self.layout,
            "has_back_face": self.has_back_face,
            "back_name": self.back_name,
            "back_type_line": self.back_type_line,
            "back_oracle_text": self.back_oracle_text,
            "back_mana_cost_string": self.back_mana_cost_string,
            "back_power": self.back_power,
            "back_toughness": self.back_toughness,
            "back_image_uri_small": self.back_image_uri_small,
            "back_image_uri_normal": self.back_image_uri_normal,
            "back_image_uri_large": self.back_image_uri_large,
            "back_image_uri_png": self.back_image_uri_png,
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
            layout=data.get("layout", ""),
            back_name=data.get("back_name", ""),
            back_type_line=data.get("back_type_line", ""),
            back_oracle_text=data.get("back_oracle_text", ""),
            back_mana_cost_string=data.get("back_mana_cost_string", ""),
            back_power=data.get("back_power"),
            back_toughness=data.get("back_toughness"),
            back_image_uri_small=data.get("back_image_uri_small", ""),
            back_image_uri_normal=data.get("back_image_uri_normal", ""),
            back_image_uri_large=data.get("back_image_uri_large", ""),
            back_image_uri_png=data.get("back_image_uri_png", ""),
        )
        # Note: "has_back_face" in the dict is a derived, read-only
        # property (see to_dict); it is intentionally not a constructor
        # argument, so from_dict ignores it and recomputes it.

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
