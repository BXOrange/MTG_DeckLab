"""Card model representing a single Magic: The Gathering card.

Reference: /docs/concepts/06_CARD_GRAPHICS_AND_LAZY_LOADING.md (PART 1)
"""

from __future__ import annotations

import re
from typing import Any, Optional

#: Colors that may legally appear in a card's color identity.
VALID_COLORS: frozenset[str] = frozenset({"W", "U", "B", "R", "G"})

#: Default mana cost used when none is supplied.
_DEFAULT_MANA_COST: dict[str, int] = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0}


def _fold_bare_name(text: str, name: str) -> str:
    """Replace whole-word occurrences of ``name`` in ``text`` with "~".

    Used by `Card.fuse_face` to pre-fold each split half's own self-reference
    before concatenating — see that method's docstring for why."""
    if not name:
        return text
    return re.sub(r"\b" + re.escape(name) + r"\b", "~", text)


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
        vehicle_power/vehicle_toughness: RULE 208.1's printed P/T for a
            noncreature permanent that only matters once it becomes a
            creature by another effect (Vehicles, RULE 702.122a Crew) — None
            for the overwhelming majority of cards, which print none while
            noncreature. Independent of power/toughness above.
        oracle_text: The card's rules text.
        keywords: Machine-readable keyword abilities parsed out of the
            oracle text (e.g. ["Flying", "Trample"]), as reported by
            Scryfall. This is a lookup table for the Phase 2 effect
            system (docs/concepts/07_GAME_LOOP_EFFECT_SYSTEM.md); it does not
            itself execute anything.
        image_uri_small: URL of the small Scryfall image.
        image_uri_normal: URL of the normal Scryfall image.
        image_uri_large: URL of the large Scryfall image.
        image_uri_png: URL of the print-quality Scryfall image.
        set_code: The set this printing is from, e.g. "ltr".
        rarity: The printing's rarity, e.g. "common", "mythic".
        flavor_name: An alternate name printed on some promo printings
            instead of/alongside the real one — Secret Lair's "Godzilla"
            series (e.g. "Godzilla, King of the Monsters" for Zilortha,
            Strength Incarnate), several Universes Beyond crossovers
            (Marvel, …). Scryfall metadata, not a distinct card or a rules
            characteristic; empty for ordinary printings. Decklists built
            from the physical card sometimes use this instead of the real
            name — `CardDatabase`/`LazyCardLoader` resolve it too.
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
        loyalty: Optional[int] = None,
        defense: Optional[int] = None,
        vehicle_power: Optional[int] = None,
        vehicle_toughness: Optional[int] = None,
        oracle_text: str = "",
        keywords: Optional[list[str]] = None,
        image_uri_small: str = "",
        image_uri_normal: str = "",
        image_uri_large: str = "",
        image_uri_png: str = "",
        set_code: str = "",
        rarity: str = "",
        flavor_name: str = "",
        is_legendary: bool = False,
        has_partner: bool = False,
        partner_with: Optional[str] = None,
        has_fuse: bool = False,
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
        #: Printed starting loyalty for a planeswalker (RULE 606.5b), or None.
        #: A planeswalker enters with this many loyalty counters.
        self.loyalty = loyalty
        #: Printed defense for a battle (RULE 310.4a), or None. A battle
        #: enters with this many defense counters (310.4b) and its *current*
        #: defense is that counter count (310.4c) — the exact shape
        #: `loyalty` has for a planeswalker, which is why the two seed
        #: through the same `RulesEngine._apply_entry_counters` path.
        self.defense = defense
        #: RULE 208.1: some noncreature permanents — Vehicles chief among
        #: them — have power/toughness printed on the card even though
        #: `is_creature` is False; those values matter only once something
        #: else (Crew, RULE 702.122a) makes the permanent a creature. Kept
        #: fully separate from `power`/`toughness` above (which stay
        #: creature-only, per this class's own invariant) rather than
        #: relaxing that invariant — every existing reader that treats
        #: "power is not None" as a creature check stays correct. ``None``
        #: for the overwhelming majority of cards, which print no P/T at
        #: all while noncreature. MEC-29's own real trigger: without this,
        #: `effect_binder._crew_activated_ability`'s "becomes an artifact
        #: creature" grant had nothing to set power/toughness from, so a
        #: freshly crewed Vehicle came in 0/0 and died to RULE 704.5f the
        #: instant a state-based action check ran.
        self.vehicle_power = vehicle_power
        self.vehicle_toughness = vehicle_toughness
        self.oracle_text = oracle_text
        self.keywords = list(keywords) if keywords is not None else []
        self.image_uri_small = image_uri_small
        self.image_uri_normal = image_uri_normal
        self.image_uri_large = image_uri_large
        self.image_uri_png = image_uri_png
        self.set_code = set_code
        self.rarity = rarity
        self.flavor_name = flavor_name
        self.is_legendary = is_legendary
        self.has_partner = has_partner
        self.partner_with = partner_with
        #: Whether this split card has Fuse (RULE 709.4 — cast both halves
        #: as one spell for their combined cost). See `fuse_face`.
        self.has_fuse = has_fuse
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
    def is_planeswalker(self) -> bool:
        """Whether the card is a planeswalker (derived from the type line).

        Scryfall gives explicit ``is_creature``/``is_land`` flags but no
        planeswalker/artifact/enchantment booleans, so these are read off
        ``type_line`` (RULE 205.2a card types). Kept as read-only derived
        properties — no stored field, so no cache-schema change.
        """
        return "planeswalker" in self.type_line.lower()

    @property
    def is_artifact(self) -> bool:
        """Whether the card is an artifact (derived from the type line)."""
        return "artifact" in self.type_line.lower()

    @property
    def is_battle(self) -> bool:
        """Whether the card is a battle (RULE 310, a card type).

        Read off the type line like `is_planeswalker`/`is_artifact` above —
        Scryfall gives no boolean for it either. "Battle" is a card type,
        never a subtype, so a bare substring test can't false-positive off
        another card's subtype line the way it could for e.g. "Saga".
        """
        return "battle" in self.type_line.lower()

    @property
    def is_siege(self) -> bool:
        """Whether the card is a Siege (RULE 310.11, the only battle subtype
        that currently exists on a real card).

        Sieges are the subtype that gets a protector chosen on entry
        (310.11a) and that exiles-and-casts-itself-transformed when defeated
        (310.11b); a battle of any *other* subtype does neither, so the
        engine branches on this rather than on `is_battle`.
        """
        return self.is_battle and "siege" in self.type_line.lower()

    @property
    def is_saga(self) -> bool:
        """Whether the card is a Saga enchantment (RULE 714, subtype Saga)."""
        return "saga" in self.type_line.lower()

    @property
    def is_class(self) -> bool:
        """Whether the card is a Class enchantment (RULE 716, subtype Class)."""
        return "class" in self.type_line.lower()

    @property
    def is_leveler(self) -> bool:
        """Whether the card is a Leveler (RULE 711 — a "Level up" ability).

        Unlike Saga/Class, Leveler isn't a printed subtype — it's identified
        by the "Level up {cost}" activated-ability line (RULE 711.4a), so
        this reads the oracle text rather than the type line.
        """
        return bool(re.search(r"^level up\b", self.oracle_text or "", re.I | re.M))

    @property
    def is_station(self) -> bool:
        """Whether the card has RULE 702.184/721 Station — a "striated"
        permanent (a Spacecraft artifact or a Planet land, so far — RULE
        721 doesn't restrict the card *type*, just requires the tiered
        "N+ | <ability>" text-box shape) whose text box gates ability
        brackets on its own charge-counter count.

        Unlike Leveler, "Station" *is* a real, reliably-present Scryfall
        keyword on every printing checked (confirmed against all 30 cached
        "Station" cards, both Spacecraft and Planet) — cheaper and more
        robust than an oracle-text regex, so this reads `keywords` instead.
        """
        return any(str(k).strip().lower() == "station" for k in (self.keywords or []))

    @property
    def is_adventure(self) -> bool:
        """Whether the card has an Adventure half (RULE 715, layout)."""
        return self.layout == "adventure"

    @property
    def is_split(self) -> bool:
        """Whether the card is a split card (RULE 709, layout)."""
        return self.layout == "split"

    @property
    def is_preparation(self) -> bool:
        """Whether the card has an inset "prepare spell" (RULE 722, layout).

        Unlike a modal DFC/Adventure/Split, the second face captured here
        (via `back_face`) is never itself castable from hand (RULE 722.3) —
        it only becomes reachable as a token copy created in exile once the
        permanent "becomes prepared" (`GameObject.prepared`,
        `RulesEngine.make_prepared`)."""
        return self.layout == "prepare"

    def back_face(self) -> Optional["Card"]:
        """The back/second face as its own `Card`, or None if there is none.

        Builds a printed-characteristics `Card` from the stored ``back_*``
        fields so the back can be cast (a modal DFC, RULE 712.10, or a
        split card's other half, RULE 709.3), transformed into on the
        battlefield (RULE 712.8), cast as an Adventure's instant/sorcery
        half (RULE 715.2b), or used as the template for a preparation
        card's exiled copy once it becomes prepared (RULE 722.3c) —
        whichever it is is distinguished by ``layout``. The two faces share
        the physical object's id; the back's derived type flags come from
        its own ``back_type_line``. Returns None when no back face was
        captured."""
        if not self.back_name and not self.back_type_line:
            return None
        btl = self.back_type_line or self.type_line
        back_is_creature = "creature" in btl.lower()
        return Card(
            id=self.id,  # same physical object (RULE 712.2)
            name=self.back_name or self.name,
            type_line=btl,
            mana_cost_string=self.back_mana_cost_string,
            converted_mana_cost=self.converted_mana_cost,
            color_identity=set(self.color_identity),
            is_creature=back_is_creature,
            is_instant="instant" in btl.lower(),
            is_sorcery="sorcery" in btl.lower(),
            is_land="land" in btl.lower(),
            power=self.back_power if back_is_creature else None,
            toughness=self.back_toughness if back_is_creature else None,
            oracle_text=self.back_oracle_text,
            is_legendary="legendary" in btl.lower(),
            layout=self.layout,
            image_uri_small=self.back_image_uri_small,
            image_uri_normal=self.back_image_uri_normal,
            image_uri_large=self.back_image_uri_large,
            image_uri_png=self.back_image_uri_png,
        )

    def fuse_face(self) -> Optional["Card"]:
        """A synthetic merged `Card` for casting both split halves as one
        spell (RULE 709.4 Fuse), or None if this card has no Fuse.

        Not a printed face — Fuse casts *the whole card* for both halves'
        combined cost, so this concatenates the two halves' raw
        ``mana_cost_string``s and ``oracle_text``s onto one `Card` sharing
        this card's own already-combined ``name``/``type_line`` (Scryfall
        gives a split card's top-level name as "A // B" already) and
        top-level ``converted_mana_cost`` (already the two halves' sum).
        `ManaCost.parse` sums every generic symbol it finds regardless of
        how many separate ``{N}`` groups they came from, so the
        concatenated cost string prices correctly with no dedicated
        cost-combining logic; likewise the oracle-text parser binds the
        concatenated text as one card's (compound) rules text, so a fused
        cast reuses the ordinary single-card cast/bind pipeline
        (`RulesEngine.switch_to_face`) rather than needing two independent
        effect sets on one stack item.

        Each half's own oracle text refers to itself by its own bare name
        (e.g. "Burn deals 2 damage..."), which the parser's self-reference
        folding (``parser.oracle.normalize``) only recognises against
        *this* `Card`'s own ``name`` — the combined "A // B" here, matching
        neither half's bare text. So each half's own name is folded to the
        ``~`` self-reference token *before* concatenating, the same
        substitution the parser would do for a card whose name actually
        matched — done locally (`_fold_bare_name`, mirroring
        ``normalize._fold_self_name``'s word-boundary rule) rather than by
        importing the parser front-end into this model."""
        if not (self.is_split and self.has_fuse and self.back_name):
            return None
        back_type_line = self.back_type_line or ""
        front_name = self.name.split("//")[0].strip()
        front_text = _fold_bare_name(self.oracle_text, front_name)
        back_text = _fold_bare_name(self.back_oracle_text, self.back_name)
        return Card(
            id=self.id,
            name=self.name,
            type_line=self.type_line,
            mana_cost_string=self.mana_cost_string + self.back_mana_cost_string,
            converted_mana_cost=self.converted_mana_cost,
            color_identity=set(self.color_identity),
            is_creature=False,
            is_instant=self.is_instant and "instant" in back_type_line.lower(),
            is_sorcery=self.is_sorcery or "sorcery" in back_type_line.lower(),
            is_land=False,
            oracle_text=f"{front_text}\n{back_text}",
            is_legendary=self.is_legendary,
            layout=self.layout,
            image_uri_small=self.image_uri_small,
            image_uri_normal=self.image_uri_normal,
            image_uri_large=self.image_uri_large,
            image_uri_png=self.image_uri_png,
        )

    @property
    def is_enchantment(self) -> bool:
        """Whether the card is an enchantment (derived from the type line)."""
        return "enchantment" in self.type_line.lower()

    def as_copy(
        self,
        add_types: Optional[list[str]] = None,
        add_subtypes: Optional[list[str]] = None,
        not_legendary: bool = False,
        only_types: Optional[list[str]] = None,
        add_keywords: Optional[list[str]] = None,
        set_power: Optional[int] = None,
        set_toughness: Optional[int] = None,
        set_colors: Optional[list[str]] = None,
    ) -> "Card":
        """This card's *copiable values* (RULE 706.2), as a fresh `Card`.

        Used by a "become a copy of target permanent" effect (RULE 707):
        name, mana cost, colour identity, card type/subtypes, rules text,
        power/toughness/loyalty, and (for board display fidelity, though not
        rules-required) the printed images — everything a copy effect
        actually copies. Deliberately excludes anything RULE 706.2 doesn't
        cover and this model tracks elsewhere on the *object*, not the card:
        counters, tapped/attached/damage state, control, summoning sickness.

        ``add_types``/``add_subtypes`` model a card's own "except it's a(n)
        X in addition to its other types" clause (Copy Artifact's
        "enchantment", Phantasmal Image's "Illusion") — types are inserted
        before the type line's em dash, subtypes after it. ``not_legendary``
        (RULE 205.4a, the "except it isn't legendary" family — Multiversal
        Recruitment/Hall of Mirrors-shaped) strips the Legendary supertype
        from both `is_legendary` and the printed type line, since some
        board/legality surfaces read the word directly rather than the flag.
        ``only_types`` is the "…except it loses all other card types" sibling
        of ``add_types`` (Imposter Mech-shaped) — replaces the type line's
        whole main-type portion (and drops the copied creature's own
        subtypes along with it, same "other card types" clause) instead of
        appending; ``add_subtypes`` still applies on top, for a card that
        both strips the original types *and* adds its own (Vehicle).
        ``set_power``/``set_toughness`` (The Jolly Balloon Man, MEC-40 —
        "…except it's a 1/1 red Balloon creature…") override the copied
        creature's own printed P/T outright, applied last so they win over
        whatever the copied card printed. ``set_colors`` (PAR-18 residue —
        "…except it's a 4/4 **black** zombie", the reanimator-token cycle:
        Anikthea/Ardyn/God-Pharaoh's Gift/Hour of Eternity) replaces the
        copied card's colour identity outright with exactly the given WUBRG
        letters (an empty list makes the copy colourless).
        ``add_keywords`` appends raw keyword strings onto the copy (Flesh
        Duplicate's conditional Vanishing, Imposter Mech's Crew) — RULE
        707.2 replaces the original's printed text with the copied object's,
        so a keyword the "except" clause grants has to be re-added here
        rather than assumed to survive.
        """
        type_line = self.type_line
        if only_types is not None:
            _, dash, sub = type_line.partition("—")
            type_line = " ".join(only_types).strip()
            if add_subtypes:
                type_line = f"{type_line} — {' '.join(add_subtypes)}".strip()
            add_subtypes = None  # already folded in above
        if add_types:
            main, dash, sub = type_line.partition("—")
            type_line = f"{main.strip()} {' '.join(add_types)}".strip()
            if dash:
                type_line = f"{type_line} — {sub.strip()}"
        if add_subtypes:
            main, dash, sub = type_line.partition("—")
            sub = f"{sub.strip()} {' '.join(add_subtypes)}".strip()
            type_line = f"{main.strip()} — {sub}" if dash or sub else main.strip()
        is_legendary = self.is_legendary
        if not_legendary:
            is_legendary = False
            main, dash, sub = type_line.partition("—")
            main = re.sub(r"\bLegendary\b\s*", "", main).strip()
            type_line = f"{main} — {sub.strip()}" if dash else main
        # PAR-30 fix (found by execute-testing Arteeoh, Dread Scavenger's
        # "…except it's a 1/1 green Squirrel creature token in addition to
        # its other types"): `add_types` naming "creature" on a non-creature
        # original (Copy Artifact-shaped "except it's an artifact **and a
        # creature**") must flip `is_creature` too, the same way the
        # `only_types` branch just below already computes it — otherwise the
        # `set_power`/`set_toughness` override further down builds a Card
        # with printed power/toughness but `is_creature=False`, tripping
        # `Card.__init__`'s own "power/toughness may only be set on
        # creatures" invariant. `only_types` (mutually exclusive with a bare
        # additive `add_types`, per its own docstring) always overrides this.
        is_creature = self.is_creature or bool(
            add_types and "creature" in {t.lower() for t in add_types}
        )
        power, toughness = self.power, self.toughness
        vehicle_power, vehicle_toughness = self.vehicle_power, self.vehicle_toughness
        if only_types is not None:
            is_creature = "creature" in {t.lower() for t in only_types} | {
                t.lower() for t in (add_types or [])
            }
            if not is_creature and self.is_creature:
                # RULE 208.1: a noncreature can't carry `power`/`toughness`
                # (`Card.__init__`'s own invariant) — the copied creature's
                # P/T is still copiable (RULE 706.2), it just moves to the
                # vehicle-style slot a Vehicle's printed P/T lives in, same
                # as `_crew_activated_ability`'s own read of this field.
                vehicle_power, vehicle_toughness = self.power, self.toughness
                power, toughness = None, None
        if set_power is not None:
            power = set_power
        if set_toughness is not None:
            toughness = set_toughness
        color_identity = (
            {c for c in set_colors if c in VALID_COLORS}
            if set_colors is not None else set(self.color_identity)
        )
        keywords = list(self.keywords)
        oracle_text = self.oracle_text
        if add_keywords:
            # `keywords_of` (combat.py) reads the bare-name list above for
            # the evasion-type subset — Scryfall's own ``keywords`` array
            # never carries a parametric keyword's number (`Aven
            # Riftwatcher`'s is ``['Flying', 'Vanishing']``, not
            # ``'Vanishing 3'``), and `parse_keywords` (`catalogue/
            # keywords.py`) slug-matches each entry verbatim — a number
            # baked into the string fails that match entirely. So the list
            # gets each entry's bare name (first word); the full string
            # (with its number) goes into `oracle_text` instead, where a
            # keyword needing its own bound ability (Vanishing's upkeep
            # trigger, Crew's activation) is actually read from — only
            # reachable by re-parsing text (`effect_binder.bind_from_
            # catalogue`, called right after this by `become_copy`), so the
            # grant has to show up there too, as a plain new keyword line,
            # exactly like a printed card's own.
            bare_names = [k.split()[0] for k in add_keywords]
            keywords.extend(n for n in bare_names if n not in keywords)
            new_lines = [k for k in add_keywords if k.lower() not in (oracle_text or "").lower()]
            if new_lines:
                oracle_text = f"{oracle_text}\n" + "\n".join(new_lines) if oracle_text else "\n".join(new_lines)
        return Card(
            id=self.id,
            name=self.name,
            type_line=type_line,
            mana_cost=dict(self.mana_cost),
            mana_cost_string=self.mana_cost_string,
            converted_mana_cost=self.converted_mana_cost,
            color_identity=color_identity,
            is_creature=is_creature,
            is_instant=self.is_instant,
            is_sorcery=self.is_sorcery,
            is_land=self.is_land,
            power=power,
            toughness=toughness,
            loyalty=self.loyalty,
            defense=self.defense,
            vehicle_power=vehicle_power,
            vehicle_toughness=vehicle_toughness,
            oracle_text=oracle_text,
            keywords=keywords,
            image_uri_small=self.image_uri_small,
            image_uri_normal=self.image_uri_normal,
            image_uri_large=self.image_uri_large,
            image_uri_png=self.image_uri_png,
            set_code=self.set_code,
            rarity=self.rarity,
            is_legendary=is_legendary,
            layout=self.layout,
            back_name=self.back_name,
            back_type_line=self.back_type_line,
            back_oracle_text=self.back_oracle_text,
            back_mana_cost_string=self.back_mana_cost_string,
            back_power=self.back_power,
            back_toughness=self.back_toughness,
            back_image_uri_small=self.back_image_uri_small,
            back_image_uri_normal=self.back_image_uri_normal,
            back_image_uri_large=self.back_image_uri_large,
            back_image_uri_png=self.back_image_uri_png,
        )

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
    def has_clean_partner_with(self) -> bool:
        """Whether `partner_with` (if set) is a bare card name.

        A row cached before a `scryfall_client._partner_with` parsing fix
        can have its RULE 207.2 reminder text still stuck on the end (e.g.
        "Frodo, Adventurous Hobbit (When this creature enters, ...)"
        instead of just "Frodo, Adventurous Hobbit") — no real card name
        contains "(", so its presence means this row predates the fix.
        `LazyCardLoader` uses this to refetch it instead of forever
        wrongly rejecting a legal Partner-with pairing
        (`services/commander_legality.py`).
        """
        return self.partner_with is None or "(" not in self.partner_with

    @property
    def has_mana_cost_data(self) -> bool:
        """Whether `mana_cost_string` reflects a real Scryfall lookup.

        Scryfall gives every non-land an explicit cost string (even a
        genuinely free one is `"{0}"`, not blank) — so a non-land card with
        a blank `mana_cost_string` means this row predates that field
        (`docs/implementation-state/Done_Backend.md` "Mana cost model"), not that the card
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
            "loyalty": self.loyalty,
            "defense": self.defense,
            "vehicle_power": self.vehicle_power,
            "vehicle_toughness": self.vehicle_toughness,
            "oracle_text": self.oracle_text,
            "keywords": list(self.keywords),
            "image_uri_small": self.image_uri_small,
            "image_uri_normal": self.image_uri_normal,
            "image_uri_large": self.image_uri_large,
            "image_uri_png": self.image_uri_png,
            "set_code": self.set_code,
            "rarity": self.rarity,
            "flavor_name": self.flavor_name,
            "is_legendary": self.is_legendary,
            "has_partner": self.has_partner,
            "partner_with": self.partner_with,
            "has_fuse": self.has_fuse,
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
            loyalty=data.get("loyalty"),
            defense=data.get("defense"),
            vehicle_power=data.get("vehicle_power"),
            vehicle_toughness=data.get("vehicle_toughness"),
            oracle_text=data.get("oracle_text", ""),
            keywords=data.get("keywords"),
            image_uri_small=data.get("image_uri_small", ""),
            image_uri_normal=data.get("image_uri_normal", ""),
            image_uri_large=data.get("image_uri_large", ""),
            image_uri_png=data.get("image_uri_png", ""),
            set_code=data.get("set_code", ""),
            rarity=data.get("rarity", ""),
            flavor_name=data.get("flavor_name", ""),
            is_legendary=data.get("is_legendary", False),
            has_partner=data.get("has_partner", False),
            partner_with=data.get("partner_with"),
            has_fuse=data.get("has_fuse", False),
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
