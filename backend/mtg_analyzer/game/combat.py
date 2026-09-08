"""Combat- and evasion-keyword recognition + the rules they impose.

Reference: RULE 509 (declaring blockers), RULE 510 (combat damage), and the
keyword-ability rules — flying 702.9, first strike 702.7, double strike
702.4, deathtouch 702.2, trample 702.19, vigilance 702.21, lifelink 702.15,
menace 702.111, reach 702.17, defender 702.3, haste 702.10, protection
702.16, indestructible 702.12.

Two jobs, kept in one pure place:

1. **Recognition** — turn a `Card`'s printed characteristics into normalized
   combat keywords. Scryfall already hands us a machine-readable ``keywords``
   list, so that is the primary source; we additionally scan ``oracle_text``
   for keyword-ability clauses (to catch tokens/cards with no ``keywords``
   field) and, crucially, to read the *parameter* of "protection from …"
   which the flat keyword list drops.

2. **Rules helpers** — the small predicates the combat engine consults:
   whether an attacker can be blocked by a given blocker (flying/reach,
   protection, and — as a group check — menace), and how a keyword shapes
   damage (first/double strike ordering, deathtouch lethality, trample
   overflow, lifelink gain, protection prevention).

Pure by design: it reads models only and holds no game state, so both the
engine (`game_engine.py`) and the wire layer (`GameObject.to_dict`) can use
it without a dependency cycle.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Optional

from ..parser.oracle.catalogue.levels import leveler_base_text
from ..parser.oracle.catalogue.station import station_base_text

if TYPE_CHECKING:  # pragma: no cover - typing only, avoids a model→game cycle
    from ..models.card import Card
    from ..models.game_object import GameObject
    from ..models.game_state import GameState

#: The combat-relevant keyword abilities we model, as canonical slugs. Other
#: keywords (e.g. flash, ward, hexproof) are recognized elsewhere or not yet;
#: this set is exactly what the combat engine reacts to.
COMBAT_KEYWORDS: frozenset[str] = frozenset(
    {
        "flying",
        "reach",
        "first_strike",
        "double_strike",
        "deathtouch",
        "trample",
        "vigilance",
        "lifelink",
        "menace",
        "defender",
        "haste",
        "indestructible",
        "protection",
        "dethrone",
        "infect",
        "wither",
        # RULE 702.19: no bare reminder-text keyword line to match on real
        # cards (it's always spelled out in full sentences), so this is
        # reached only via the Scryfall `keywords` list, never
        # `_ORACLE_PATTERNS` — see `game/engine/combat_mixin.py`'s
        # `declare_attackers`.
        "exert",
    }
)

#: Colour word → single-letter identity, for "protection from <colour>".
_COLOUR_WORDS: dict[str, str] = {
    "white": "W",
    "blue": "U",
    "black": "B",
    "red": "R",
    "green": "G",
}

#: The basic land types a ``<type>walk`` keyword can name (RULE 702.14 / 305.6).
#: A slug like ``"islandwalk"`` (from Scryfall's keyword list, the card's
#: oracle text, or a bound landwalk keyword spec) maps to its subtype prefix.
_LAND_SUBTYPES: frozenset[str] = frozenset(
    {"plains", "island", "swamp", "mountain", "forest"}
)


def _normalize(keyword: str) -> str:
    """A Scryfall keyword string → our slug ("First strike" → "first_strike")."""
    return keyword.strip().lower().replace(" ", "_").replace("-", "_")


#: Keyword slug → a regex matching that ability as its *own* clause in oracle
#: text (start of text/line, or after a comma/semicolon), so "gains flying"
#: or "target creature gains trample" — an effect that *grants* a keyword,
#: not the card having it — does not register a false positive.
_ORACLE_PATTERNS: dict[str, re.Pattern[str]] = {
    slug: re.compile(rf"(?:^|[\n;,]|\.\s)\s*{phrase}\b")
    for slug, phrase in {
        "flying": "flying",
        "reach": "reach",
        "first_strike": "first strike",
        "double_strike": "double strike",
        "deathtouch": "deathtouch",
        "trample": "trample",
        "vigilance": "vigilance",
        "lifelink": "lifelink",
        "menace": "menace",
        "defender": "defender",
        "haste": "haste",
        "indestructible": "indestructible",
        "infect": "infect",
        "wither": "wither",
    }.items()
}

#: "protection from <quality>" up to the clause end (a period/comma/semicolon/
#: newline or end of text). Official templating repeats "from" for each
#: quality on a multi-protection permanent ("Protection from red and from
#: blue" — the Sword-of-X-and-Y cycle), so the *clause* is captured whole and
#: `protections_of` splits it on " and from " to recover each quality.
_PROTECTION_RE = re.compile(r"protection from ([a-z][a-z ]*?)(?=[.,;\n]|$)")

#: "protection from <quality>" qualities that name a card type rather than a
#: colour/"creatures"/blanket form, mapped to the `Card` attribute that
#: answers whether a source has that type (RULE 702.16, e.g. "protection from
#: artifacts").
_CARD_TYPE_PROTECTIONS: dict[str, str] = {
    "artifacts": "is_artifact",
    "enchantments": "is_enchantment",
    "planeswalkers": "is_planeswalker",
    "lands": "is_land",
    "instants": "is_instant",
    "sorceries": "is_sorcery",
}


def keywords_of(card: "Card") -> frozenset[str]:
    """The combat keywords `card` has, from its ``keywords`` list + oracle text.

    The Scryfall ``keywords`` list is authoritative when present; the oracle
    scan is a clause-anchored fallback that also covers tokens built without a
    keyword list. "Protection" is included here as a bare flag; *what* it is
    from lives in `protections_of`.

    A Leveler's (RULE 711.4c) ``keywords`` array and oracle text both cover
    its *whole* printed text, tier or not — so a keyword printed only under a
    ``LEVEL`` block (e.g. Kargan Dragonlord's "Flying, haste" under
    "LEVEL 7+") would otherwise register here as always-on. Restrict both to
    the pre-``LEVEL`` base text instead — the same cross-check
    `catalogue.keywords.parse_keywords` applies to the intrinsic-keyword bind
    — so a tier-only keyword only shows up via its level-gated
    `granted_keywords` grant (`continuous.recompute`), not unconditionally.

    A Station permanent's (RULE 721) own ``"N+ | <ability>"`` brackets are
    the same shape — confirmed live on Entropic Battlecruiser, whose "8+ |
    Flying, deathtouch" bracket leaked a permanent, unconditional
    `deathtouch` (comma-anchored, so it matched `_ORACLE_PATTERNS` even at 0
    charge counters) despite Scryfall's own ``keywords`` array for every
    cached Station card never listing a bracket-only keyword in the first
    place (so only the oracle-text fallback needs the fix, not the printed-
    keywords loop below). `station_base_text` filters the bracket lines out
    rather than truncating (RULE 721.4 allows a real, unconditional
    bracket-less line *after* the brackets too, unlike Leveler's strict
    preamble-then-blocks shape).
    """
    is_leveler = bool(getattr(card, "is_leveler", False))
    is_station = bool(getattr(card, "is_station", False))
    raw_text = getattr(card, "oracle_text", "") or ""
    if is_leveler:
        scan_text = leveler_base_text(raw_text)
    elif is_station:
        scan_text = station_base_text(raw_text)
    else:
        scan_text = raw_text

    found: set[str] = set()
    for kw in getattr(card, "keywords", None) or []:
        slug = _normalize(str(kw))
        if slug not in COMBAT_KEYWORDS:
            continue
        if is_leveler and not re.search(rf"\b{re.escape(str(kw))}\b", scan_text, re.I):
            continue
        found.add(slug)
    text = scan_text.lower()
    if text:
        for slug, pattern in _ORACLE_PATTERNS.items():
            if pattern.search(text):
                found.add(slug)
        if _PROTECTION_RE.search(text):
            found.add("protection")
    return frozenset(found)


def protections_of_text(text: str) -> frozenset[str]:
    """The qualities a raw oracle-text string grants protection from, as
    normalized tokens.

    Colours collapse to identity letters (``"red"`` → ``"R"``); the blanket
    forms map to sentinels (``"everything"``, ``"all_colors"``); object-type
    qualities are kept as words (``"creatures"``, ``"artifacts"``). Combat
    only consults colour, ``"creatures"``, ``"all_colors"`` and
    ``"everything"``; the rest are recognized so nothing is silently dropped.
    Takes a plain string (rather than a `Card`) so a layer-3 "text_change"
    static ability's rewritten text (`GameObject.effective_oracle_text`) can
    be checked the same way as a card's printed text (`protections_of`).
    """
    text = (text or "").lower()
    quals: set[str] = set()
    for match in _PROTECTION_RE.finditer(text):
        clause = match.group(1)
        for quality in re.split(r"\s+and\s+from\s+", clause):
            quality = quality.strip()
            if not quality:
                continue
            if quality in ("everything",):
                quals.add("everything")
            elif quality in ("all colors", "all colours"):
                quals.add("all_colors")
            elif quality in _COLOUR_WORDS:
                quals.add(_COLOUR_WORDS[quality])
            else:
                quals.add(quality)
    return frozenset(quals)


def protections_of(card: "Card") -> frozenset[str]:
    """The qualities `card` has protection from — `protections_of_text`
    over its printed ``oracle_text``. See `is_protected_from` for the
    per-object variant that also honours a layer-3 text-changing effect."""
    return protections_of_text(getattr(card, "oracle_text", "") or "")


# --- Per-object predicates ---------------------------------------------------
# Thin readers over an object's printed card so the engine reads intent, not
# string sets. Each recomputes from the card (cheap; no per-object cache to
# invalidate on a copy/rewind).


def _obj_keywords(obj: "GameObject") -> frozenset[str]:
    # Three sources, unioned: the card's recognized keywords, the flag keywords
    # the parser catalogue bound onto the object (`intrinsic_keywords`, RULE
    # 702), and any granted by a layer-6 static ability (RULE 613.7f) — so both
    # a card's own flying and an anthem that hands out flying flow into combat.
    # A layer-6 "loses <keyword>" static ability (`removed_keywords`,
    # Colossus Hammer) is subtracted last, after the union — RULE 613.7f
    # ability-removal applies regardless of which of the three sources
    # granted the keyword in the first place.
    # RULE 613.7f: a "loses all abilities" static ability (Humility, Dress
    # Down) strips every keyword — including the object's own printed ones —
    # regardless of source. Granted keywords from a *lower-timestamp* effect
    # would layer back on in real rules, but no cube card stacks a grant over
    # Humility, so the simple "all gone" answer is correct here.
    if getattr(obj, "loses_all_abilities", False):
        return frozenset()
    return (
        keywords_of(obj.card)
        | frozenset(getattr(obj, "intrinsic_keywords", set()) or set())
        | frozenset(getattr(obj, "granted_keywords", set()) or set())
    ) - frozenset(getattr(obj, "removed_keywords", set()) or set())


def has(obj: "GameObject", keyword: str) -> bool:
    return keyword in _obj_keywords(obj)


def has_flying(obj: "GameObject") -> bool:
    return "flying" in _obj_keywords(obj)


def has_reach(obj: "GameObject") -> bool:
    return "reach" in _obj_keywords(obj)


def has_first_strike(obj: "GameObject") -> bool:
    return "first_strike" in _obj_keywords(obj)


def has_double_strike(obj: "GameObject") -> bool:
    return "double_strike" in _obj_keywords(obj)


def has_deathtouch(obj: "GameObject") -> bool:
    return "deathtouch" in _obj_keywords(obj)


def has_trample(obj: "GameObject") -> bool:
    return "trample" in _obj_keywords(obj)


def has_vigilance(obj: "GameObject") -> bool:
    return "vigilance" in _obj_keywords(obj)


def has_lifelink(obj: "GameObject") -> bool:
    return "lifelink" in _obj_keywords(obj)


def has_menace(obj: "GameObject") -> bool:
    # RULE 701.60b: a suspected creature has menace (in addition to any
    # printed/granted keyword), so `min_blockers` requires 2+ blockers for it.
    return "menace" in _obj_keywords(obj) or bool(getattr(obj, "is_suspected", False))


def has_defender(obj: "GameObject") -> bool:
    return "defender" in _obj_keywords(obj)


def has_haste(obj: "GameObject") -> bool:
    return "haste" in _obj_keywords(obj)


def has_indestructible(obj: "GameObject") -> bool:
    return "indestructible" in _obj_keywords(obj)


def has_infect(obj: "GameObject") -> bool:
    return "infect" in _obj_keywords(obj)


def has_wither(obj: "GameObject") -> bool:
    return "wither" in _obj_keywords(obj)


def has_toxic(obj: "GameObject") -> bool:
    """RULE 702.164a: whether ``obj`` has Toxic N (any N). Toxic is a
    ``NUMBER``-shaped parametric keyword (`docs/09` — like Annihilator/
    Afflict/Kicker), so unlike the flag keywords above it never joins
    `_obj_keywords`; `effect_binder.attach_keyword` docks it onto
    `GameObject.parametric_keywords["toxic"] = {"n": N}` instead, which
    `toxic_value` reads back live at damage-application time."""
    return toxic_value(obj) is not None


def toxic_value(obj: "GameObject") -> Optional[int]:
    """The N in ``obj``'s Toxic N (RULE 702.164a), or ``None`` if it doesn't
    have the keyword.

    RULE 702.164b's "total toxic value" sums every toxic ability an object
    has. `parametric_keyword_value` (ENG-31) reads a *granted* "toxic N"
    (`_granted_parametric_keywords`, from a layer-6 or until-EOT grant)
    ahead of the printed value docked by `attach_keyword`; there's still no
    card that both prints and is granted toxic, so this stays a single N
    rather than a real 702.164b sum. Consulted by `RulesEngine.deal_damage`
    (RULE 702.164c), never by this module's own combat predicates.
    """
    if getattr(obj, "loses_all_abilities", False):
        return None
    getter = getattr(obj, "parametric_keyword_value", None)
    n = getter("toxic") if callable(getter) else (
        (getattr(obj, "parametric_keywords", None) or {}).get("toxic") or {}
    ).get("n")
    if n is None:
        return None
    try:
        value = int(n)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def has_hexproof(obj: "GameObject") -> bool:
    """RULE 702.11b: can't be the target of a spell/ability an opponent
    controls (an opponent's own permanents/self-targets are unaffected —
    unlike protection, hexproof never stops its own controller). Not a
    "combat" keyword in the RULE 702 evasion sense (it doesn't shape
    blocking/damage), but lives here so it reads off the same
    `_obj_keywords` union (card + `intrinsic_keywords` the parser catalogue
    docks a flag keyword onto + `granted_keywords`) every other keyword
    predicate in this module already does, instead of a second recognition
    path. `targeting.py` is the sole consumer (`_targetable_by`)."""
    return "hexproof" in _obj_keywords(obj)


def has_shroud(obj: "GameObject") -> bool:
    """RULE 702.18b: can't be the target of spells or abilities at all —
    unlike hexproof, shroud stops the permanent's *own* controller too. Like
    hexproof it isn't an evasion keyword (it doesn't shape blocking/damage);
    `targeting._targetable_by` is the sole consumer. (PAR-22)"""
    return "shroud" in _obj_keywords(obj)


def has_fear(obj: "GameObject") -> bool:
    """RULE 702.36b: an attacker with fear can be blocked only by artifact
    and/or black creatures. Consumed by `can_block` below. (PAR-22)"""
    return "fear" in _obj_keywords(obj)


def has_intimidate(obj: "GameObject") -> bool:
    """RULE 702.13b: an attacker with intimidate can be blocked only by
    artifact creatures and/or creatures that share a colour with it. (PAR-22)"""
    return "intimidate" in _obj_keywords(obj)


def has_skulk(obj: "GameObject") -> bool:
    """RULE 702.118b: a creature with skulk can't be blocked by creatures
    with greater power. (PAR-22)"""
    return "skulk" in _obj_keywords(obj)


def has_shadow(obj: "GameObject") -> bool:
    """RULE 702.28b/c: a creature with shadow can block or be blocked by only
    creatures with shadow, and a creature without shadow can't block a
    creature with shadow — the restriction runs both ways. (PAR-22)"""
    return "shadow" in _obj_keywords(obj)


def _obj_colours(obj: "GameObject") -> set[str]:
    """``obj``'s effective colours as upper-case WUBRG letters (RULE 105 /
    layer 5), the same read every colour check in this module already does
    inline off ``getattr(obj, "colors", ...)``."""
    return {str(c).upper() for c in (getattr(obj, "colors", None) or set())}


def _is_artifact(obj: "GameObject") -> bool:
    """Whether ``obj`` is currently an artifact (RULE 613 layer 4 aware —
    reads the derived ``type_words`` set, falling back to the printed card
    for a bare object with no layer pass run)."""
    words = getattr(obj, "type_words", None)
    if words is not None:
        return "artifact" in words
    return bool(getattr(getattr(obj, "card", None), "is_artifact", False))


# -- Parameterized combat restrictions (RULE 508.1a / 509.1b) ---------------
#
# The plain "~ can't attack."/"can't block."/"can't be blocked." statics are
# synthetic flag keywords (`cant_attack`/`cant_block`/`cant_be_blocked`),
# because a flag is all they need. Their *qualified* siblings — "can't be
# blocked by creatures with power 2 or less", "can't be blocked except by
# Walls", "can't attack unless defending player controls an Island", "can't
# attack alone" — carry a parameter no flag can hold, so they ride a small
# clamped param dict instead (`GameObject.combat_restrictions`, stamped every
# `continuous.recompute` pass from a ``combat_restriction`` `StaticAbility`).
#
# Evaluated at *combat time* rather than recompute time: the two things these
# depend on — who's defending, and who else is attacking — don't exist yet
# when the layer engine runs. The predicates below are the pure half (the
# ones answerable from the two creatures alone); the board/turn-scoped
# ``unless`` conditions need `GameState`, so they live in `GameEngine`
# (`_combat_condition_met`) rather than here.

#: The restriction ``kind`` vocabulary — a whitelist, like every other spec
#: string that crosses the parser→engine boundary (docs/09). Unknown kinds
#: are ignored on sight rather than guessed at.
COMBAT_RESTRICTIONS: frozenset[str] = frozenset(
    {
        # Attacker-side blocking restrictions (RULE 509.1b evasion):
        "cant_be_blocked_by",  # "…by creatures with power 2 or less" (+ ``filter``)
        "only_blocked_by",  # "…except by Walls" (+ ``filter``) — the inverse
        "max_blockers",  # "…by more than one creature" (+ ``count``)
        "min_blockers",  # "…except by two or more creatures" (+ ``count``)
        "cant_be_blocked_if_attacking_alone",  # "…as long as it's attacking alone"
        # Blocker-side restrictions — the same two set shapes, but printed on
        # the creature doing the blocking (RULE 509.1a):
        "can_block_only",  # "~ can block only creatures with flying." (+ ``filter``)
        "cant_block_filtered",  # "~ can't block creatures with power 3 or greater."
        # A blocking restriction checked against the *blocker's own*
        # characteristics rather than the attacker's — "Your opponents
        # can't block with creatures with even mana values." (Void
        # Winnower). Every other blocker-side kind above filters the
        # attacker being (dis)qualified; this one has no attacker-shaped
        # test at all, so it's kept as its own kind rather than overloading
        # ``cant_block_filtered``'s existing attacker-filter meaning.
        "cant_block_self_filtered",
        # Attack/block *permission* restrictions (RULE 508.1a/509.1a):
        "cant_attack_unless",  # + ``condition``
        "cant_block_unless",  # + ``condition``
        "cant_attack_alone",  # needs a fellow attacker
        "cant_block_alone",  # needs a fellow blocker
        # RULE 509.1b multi-block *permissions* — the mirror image of a
        # restriction (they widen what's legal rather than narrow it), but
        # ride the same param-dict/`combat_restriction` static plumbing since
        # neither changes a characteristic (`game_engine.max_blocks_for`):
        "extra_blocks",  # "~ can block an additional creature each combat." (+ ``count``)
        "unlimited_blocks",  # "~ can block any number of creatures."
        # RULE 508.1a's *attack* permission — "~ can attack as though it
        # didn't have defender" (Colossus of Akros, Tower Defense, ~15 real
        # cards). Not the removal of the Defender keyword (RULE 702.3b): the
        # creature keeps it — it still can't be declared as an attacker by
        # anything else that reads the keyword, and losing it would also lift
        # any other "creatures with defender…" clause. `GameEngine._can_attack`
        # consults this alongside `has_defender` instead.
        "attacks_as_though_no_defender",
        # RULE 509.1a's resolve-time pairwise requirement — "target creature
        # blocks ~ this turn if able" (`GrantCombatRestrictionEffect`'s
        # ``restrict_to_source``, `filter={"instance_id": <the attacker>}`) —
        # checked by `GameEngine._enforce_block_requirements`, not by anything
        # in this module (it needs the whole board, not just two creatures).
        "must_block_target",
    }
)

#: The ``filter`` key vocabulary a blocking restriction narrows by — a
#: superset of `targeting.TargetSpec.creature_filter`'s own keys (which
#: delegates here, so the two can't drift). All AND-combined; the ``*_any``
#: keys are an OR *within* themselves ("creatures with flying or reach").
#: ``power_vs_reference`` is the one relative key ("creatures with greater
#: power" — greater than the *attacker*, supplied as ``reference``).
_FILTER_KEYS: frozenset[str] = frozenset(
    {
        "min_power", "max_power", "min_toughness", "max_toughness",
        "keyword", "keyword_any", "without_keyword",
        "subtype", "subtype_any", "without_subtype", "color", "without_color",
        "card_type", "without_card_type", "power_vs_reference", "attacking",
        # "…that's blocking" / "…that's attacking or blocking" (Surge of
        # Righteousness) — RULE 509.1 blocker status and the either-of pair,
        # the siblings of the ``attacking`` boolean above.
        "blocking", "attacking_or_blocking",
        # "…if it targets a tapped creature" (RULE 601.2f cost reduction).
        "tapped",
        "even_mana_value",
        # "a black or red source"/"a source of the chosen colour"/"a creature
        # of the chosen type" (MEC-30 — Greater Realm of Preservation/Story
        # Circle/Prismatic Circle/Circle of Solace).
        "color_any", "color_from_source", "subtype_from_source",
        # RULE 111.9 — "a **nontoken** blue creature" (Flare of Denial-
        # shaped RULE 118.9 alternative cost).
        "nontoken",
        # Engine-internal only — never produced by the oracle-text parser
        # (which can't know a specific game object's id), only computed at
        # resolve time by `GrantCombatRestrictionEffect`'s ``restrict_to_source``
        # ("target creature can't block ~ this turn" / "…blocks ~ … if able").
        "instance_id",
        # A dynamic threshold instead of a literal int ("Creatures with power
        # less than the number of Islands you control can't block ~." —
        # Kraken of the Straits-shaped): the `continuous.count_selector`
        # vocabulary, evaluated fresh at combat time against the *reference*
        # object's controller (the ability's own source — Kraken, not the
        # blocker being checked — RULE 613.7c "you" always means the source's
        # controller), rather than a fixed int baked in at parse time.
        "power_lt_count_selector",
        # "**another** Dinosaur you control" (Temple Altisaur's own
        # damage-prevention recipient scoping) — the negated sibling of
        # ``instance_id`` above, excluding one specific object (always the
        # filtering ability's own source) rather than requiring one.
        "without_instance_id",
        # "Equip commander {N}" (RULE 702.6e, Commander's Plate, MEC-43) —
        # RULE 903.4's designation, not a subtype/colour word, so it needs
        # its own key rather than reusing ``subtype``.
        "is_commander",
    }
)


def matches_object_filter(
    obj: "GameObject",
    filt: "Optional[dict[str, Any]]",
    reference: "Optional[GameObject]" = None,
    state: "Optional[GameState]" = None,
) -> bool:
    """Whether ``obj`` satisfies a characteristic ``filt`` (see `_FILTER_KEYS`).

    An empty/``None`` filter matches everything. Reads *derived* power/
    toughness and the `_obj_keywords` union, so a layer-engine pass (anthems,
    counters, keyword grants) is honoured — "can't be blocked by creatures
    with power 2 or less" has to see the anthem that just pushed a blocker to
    3 power. ``reference`` is the other creature in the comparison, needed
    only by ``power_vs_reference`` and ``power_lt_count_selector``.
    ``state`` is only needed by ``power_lt_count_selector`` (has to walk the
    whole battlefield); every other key answers from ``obj``/``reference``
    alone, so callers without a state in hand can keep omitting it.
    """
    if not filt:
        return True
    min_power = filt.get("min_power")
    if min_power is not None and (obj.power or 0) < min_power:
        return False
    max_power = filt.get("max_power")
    if max_power is not None and (obj.power or 0) > max_power:
        return False
    min_toughness = filt.get("min_toughness")
    if min_toughness is not None and (obj.toughness or 0) < min_toughness:
        return False
    max_toughness = filt.get("max_toughness")
    if max_toughness is not None and (obj.toughness or 0) > max_toughness:
        return False
    keyword = filt.get("keyword")
    if keyword is not None and not has(obj, str(keyword)):
        return False
    # "destroy target creature **with a -1/-1 counter on it**" (Liliana,
    # Death Wielder's -3) / "…with a counter on it" (the kindless form) —
    # RULE 122: reads `GameObject.counters` directly, so a layer pass isn't
    # needed (counters aren't a continuous effect).
    has_counter_kind = filt.get("has_counter_kind")
    if has_counter_kind is not None and (getattr(obj, "counters", {}) or {}).get(
        str(has_counter_kind), 0
    ) <= 0:
        return False
    if filt.get("has_counter") and not any(
        v > 0 for v in (getattr(obj, "counters", {}) or {}).values()
    ):
        return False
    keyword_any = filt.get("keyword_any")
    if keyword_any and not any(has(obj, str(k)) for k in keyword_any):
        return False
    without = filt.get("without_keyword")
    if without is not None and has(obj, str(without)):
        return False
    subtype = filt.get("subtype")
    if subtype is not None and not _has_subtype(obj, str(subtype)):
        return False
    subtype_any = filt.get("subtype_any")
    if subtype_any and not any(_has_subtype(obj, str(s)) for s in subtype_any):
        return False
    # "target non-Angel creature" (Restoration Angel-shaped) — the negated
    # sibling of ``subtype`` above, same ``without_card_type`` idiom.
    without_subtype = filt.get("without_subtype")
    if without_subtype is not None and _has_subtype(obj, str(without_subtype)):
        return False
    # "target attacking Elf you control gains deathtouch until end of
    # turn." (Gnarlroot Trapper-shaped) — RULE 506.4's own attacker status,
    # composing with the subtype/"you control" filters above rather than
    # a bespoke target kind.
    if filt.get("attacking") and not getattr(obj, "attacking", False):
        return False
    # "…that's blocking" / "…that's attacking or blocking" (Surge of
    # Righteousness) — RULE 509.1: a creature is blocking once it has been
    # assigned to an attacker (`blocking`/`additional_blocking`).
    _is_blocking = bool(blocking_attacker_ids(obj))
    if filt.get("blocking") and not _is_blocking:
        return False
    if filt.get("attacking_or_blocking") and not (
        getattr(obj, "attacking", False) or _is_blocking
    ):
        return False
    # "…if it targets a **tapped** creature" (Ajani's Response / the
    # cost-less-if-it-targets cycle) — RULE 601.2f cost reduction gated on
    # the chosen target's tap state, a boolean flag like `attacking` above.
    if filt.get("tapped") is not None and bool(getattr(obj, "tapped", False)) != bool(filt["tapped"]):
        return False
    # "Equip commander {N}" (RULE 702.6e, Commander's Plate, MEC-43) — the
    # target of this Equip cost must be a commander (RULE 903.4).
    if filt.get("is_commander") and not getattr(obj, "is_commander", False):
        return False
    # "sacrifice a **nontoken** blue creature" (Flare of Denial's own RULE
    # 118.9 alternative cost) — RULE 111.9's token/nontoken distinction,
    # composing with every other filter key here rather than a bespoke
    # sacrifice-only check.
    if filt.get("nontoken") and getattr(obj, "is_token", False):
        return False
    if filt.get("token") and not getattr(obj, "is_token", False):
        return False
    # "exchange control of two target **nonlegendary** creatures" (RULE
    # 205.4a, PAR-30 — Djinn of Infinite Deceits) — reads `Card.is_legendary`
    # the same boolean-flag way `nontoken` reads `is_token` above.
    if filt.get("nonlegendary") and getattr(obj.card, "is_legendary", False):
        return False
    # "target suspected creature you control" (RULE 701.60, PAR-29 — Deadly
    # Complication) — reads `GameObject.is_suspected` the same boolean-flag
    # way `attacking`/`is_commander` do above.
    if filt.get("is_suspected") and not is_suspected(obj):
        return False
    color = filt.get("color")
    if color is not None and str(color).upper() not in {
        str(c).upper() for c in (getattr(obj, "colors", None) or set())
    }:
        return False
    # "a black **or red** source of your choice" (Greater Realm of
    # Preservation/Penance-shaped, MEC-30) — the multi-colour sibling of
    # ``color`` above, same "any of" idiom as ``keyword_any``/``subtype_any``.
    color_any = filt.get("color_any")
    if color_any:
        obj_colors = {str(c).upper() for c in (getattr(obj, "colors", None) or set())}
        if not any(str(c).upper() in obj_colors for c in color_any):
            return False
    # "a source of your choice **of the chosen colour**" (Story Circle/
    # Prismatic Circle's RULE 601.2b ETB colour choice, MEC-30) — reads
    # ``reference.chosen_color`` (the filtering ability's own source, not the
    # candidate) instead of a literal colour baked in at parse time, the same
    # dynamic-vs-literal split ``power_lt_count_selector`` already uses.
    if filt.get("color_from_source"):
        chosen = getattr(reference, "chosen_color", None) if reference is not None else None
        if not chosen or str(chosen).upper() not in {
            str(c).upper() for c in (getattr(obj, "colors", None) or set())
        }:
            return False
    # "a creature **of the chosen type**" (Circle of Solace's RULE 601.2b
    # ETB creature-type choice, MEC-30) — ``subtype``'s dynamic sibling,
    # mirroring ``color_from_source`` immediately above.
    if filt.get("subtype_from_source"):
        chosen = getattr(reference, "chosen_type", None) if reference is not None else None
        if not chosen or not _has_subtype(obj, str(chosen)):
            return False
    # "creatures with even mana values" (Void Winnower — "Zero is even.").
    # Reads the printed card's own mana value, matching how a spell's mana
    # value is looked up before layer-engine effects (see `_spell_type_
    # matches`'s sibling ``cast_prohibition`` check for the spell-side twin
    # of this same filter).
    even_mana_value = filt.get("even_mana_value")
    if even_mana_value is not None and (obj.card.converted_mana_cost % 2 == 0) != bool(even_mana_value):
        return False
    # "destroy target **nonblack** creature" (Doom Blade-shaped, RULE 105's
    # colour-hoser adjective negated) — the negated sibling of ``color``
    # above, same ``without_card_type`` idiom.
    without_color = filt.get("without_color")
    if without_color is not None and str(without_color).upper() in {
        str(c).upper() for c in (getattr(obj, "colors", None) or set())
    }:
        return False
    card_type = filt.get("card_type")
    if card_type is not None and str(card_type).lower() not in {
        str(w).lower() for w in (getattr(obj, "type_words", None) or set())
    }:
        return False
    # "destroy target **nonartifact** creature" (Go for the Throat-shaped) —
    # the negated sibling of ``card_type`` above, same ``without_keyword``
    # idiom.
    without_card_type = filt.get("without_card_type")
    if without_card_type is not None and str(without_card_type).lower() in {
        str(w).lower() for w in (getattr(obj, "type_words", None) or set())
    }:
        return False
    relation = filt.get("power_vs_reference")
    if relation is not None:
        if reference is None:
            return False
        if relation == "greater" and (obj.power or 0) <= (reference.power or 0):
            return False
        if relation == "less" and (obj.power or 0) >= (reference.power or 0):
            return False
    instance_id = filt.get("instance_id")
    if instance_id is not None and obj.instance_id != instance_id:
        return False
    without_instance_id = filt.get("without_instance_id")
    if without_instance_id is not None and obj.instance_id == without_instance_id:
        return False
    lt_selector = filt.get("power_lt_count_selector")
    if lt_selector is not None:
        if state is None or reference is None:
            return False
        from .continuous import count_selector  # function-scoped: see `_has_subtype` above

        threshold = count_selector(state, reference.controller_id, str(lt_selector))
        if (obj.power or 0) >= threshold:
            return False
    return True


def _has_subtype(obj: "GameObject", subtype: str) -> bool:
    # RULE 205.3/613.4a/613.5 + changeling — one authority for the whole
    # engine, so "can't be blocked by Walls" sees exactly the same subtypes a
    # Wall-scoped anthem does. Function-scoped import: `continuous` reaches
    # back into `effects`, which reads this module, so a top-level import
    # here would close a cycle.
    from .continuous import has_subtype

    return has_subtype(obj, subtype)


def combat_restrictions(obj: "GameObject", kind: str) -> list["dict[str, Any]"]:
    """The ``kind`` entries of ``obj``'s combat restrictions — the standing
    ones re-derived every `continuous.recompute` pass *and* any granted
    "until end of turn" by a resolving effect (`GameObject.
    temp_combat_restrictions`), which read identically here."""
    entries = list(getattr(obj, "combat_restrictions", None) or [])
    entries += list(getattr(obj, "temp_combat_restrictions", None) or [])
    return [
        entry for entry in entries
        if entry.get("kind") == kind and kind in COMBAT_RESTRICTIONS
    ]


def goaders(obj: "GameObject") -> set[str]:
    """RULE 701.15b: every player who currently has ``obj`` goaded.

    Three sources, read as one set the same way `combat_restrictions` above
    unions its standing and until-end-of-turn halves: `GameObject.goaded_by`
    (the resolve-time designation from "Goad target creature", expiring at
    the goader's next turn per 701.15a), `goaded_permanently` (the same
    designation from a "…goaded for the rest of the game" clause, which the
    turn-begin sweep never touches) and `_goaded_by_static` (re-derived
    every `continuous.recompute` from a standing "…is goaded" static, so it
    vanishes with its Aura). RULE 701.15c/d fall out of it being a set:
    several goaders each add a requirement, the same one twice adds nothing.
    """
    return (
        set(getattr(obj, "goaded_by", None) or set())
        | set(getattr(obj, "goaded_permanently", None) or set())
        | set(getattr(obj, "_goaded_by_static", None) or set())
    )


def is_goaded(obj: "GameObject") -> bool:
    """Whether ``obj`` is goaded by anyone (RULE 701.15b)."""
    return bool(goaders(obj))


def is_suspected(obj: "GameObject") -> bool:
    """RULE 701.60a: whether ``obj`` carries the **suspected** designation.

    A plain `GameObject.is_suspected` flag (`RulesEngine.suspect` sets it,
    `RemoveSuspectedEffect` clears it), not a keyword and not read from the
    layer engine — its two rules consequences (RULE 701.60b: menace, and
    can't block) are applied by `has_menace` and `combat_mixin._can_block`
    consulting this directly, mirroring how `is_goaded` feeds the
    combat-requirement checks.
    """
    return bool(getattr(obj, "is_suspected", False))


def is_detained(obj: "GameObject") -> bool:
    """RULE 701.35b: whether ``obj`` is currently **detained** by anyone.

    Reads `GameObject.detained_by` (a set of detaining players, expiring at
    each detainer's next turn — `GameEngine.begin_turn`). Its three
    consequences — can't attack, can't block, activated abilities can't be
    activated — are applied by `_can_attack` / `can_block` / `can_activate`
    consulting this, the same way `is_goaded` feeds the combat-requirement
    checks and `is_suspected` feeds the menace/can't-block ones.
    """
    return bool(getattr(obj, "detained_by", None))


def blocker_allowed(
    attacker: "GameObject", blocker: "GameObject", state: "Optional[GameState]" = None
) -> bool:
    """RULE 509.1b: whether a *qualified* blocking restriction on ``attacker``
    rules ``blocker`` out — "can't be blocked by creatures with power 3 or
    greater" (a forbidden set) or "can't be blocked except by Walls" (a
    permitted set). The parameterized sibling of `can_block` above, kept
    separate because it reads `GameObject.combat_restrictions` rather than
    the keyword union. ``state`` is only needed by a
    ``power_lt_count_selector`` filter (Kraken of the Straits-shaped); every
    other filter kind ignores it.
    """
    for entry in combat_restrictions(attacker, "cant_be_blocked_by"):
        if matches_object_filter(blocker, entry.get("filter"), reference=attacker, state=state):
            return False
    for entry in combat_restrictions(attacker, "only_blocked_by"):
        if not matches_object_filter(blocker, entry.get("filter"), reference=attacker, state=state):
            return False
    return True


def blocker_may_block(blocker: "GameObject", attacker: "GameObject") -> bool:
    """RULE 509.1a: whether a qualified restriction printed on ``blocker``
    itself rules out blocking ``attacker`` — "~ can block only creatures with
    flying" (a permitted set) or "~ can't block creatures with power 3 or
    greater" (a forbidden one).

    The mirror image of `blocker_allowed` above, which reads the restrictions
    on the *attacker*; both are consulted by `GameEngine.can_block`.
    """
    for entry in combat_restrictions(blocker, "can_block_only"):
        if not matches_object_filter(attacker, entry.get("filter"), reference=blocker):
            return False
    for entry in combat_restrictions(blocker, "cant_block_filtered"):
        if matches_object_filter(attacker, entry.get("filter"), reference=blocker):
            return False
    for entry in combat_restrictions(blocker, "cant_block_self_filtered"):
        if matches_object_filter(blocker, entry.get("filter")):
            return False
    return True


def min_blockers(obj: "GameObject") -> int:
    """How many creatures must block ``obj`` for the block to be legal.

    2 for a menacing attacker (RULE 702.111b: "can't be blocked except by two
    or more creatures"), otherwise 1 — and the same clause printed in full on
    a card without the keyword ("~ can't be blocked except by three or more
    creatures", Kraken of the Straits-shaped) raises it further via a
    ``min_blockers`` combat restriction. The largest requirement wins.
    """
    floor = 2 if has_menace(obj) else 1
    for entry in combat_restrictions(obj, "min_blockers"):
        floor = max(floor, int(entry.get("count", 2)))
    return floor


def max_blockers(obj: "GameObject") -> "Optional[int]":
    """How many creatures may block ``obj`` at most (RULE 509.1b, "~ can't be
    blocked by more than one creature" — Bristling Boar-shaped), or ``None``
    for no cap. The smallest cap in play wins.
    """
    caps = [int(e.get("count", 1)) for e in combat_restrictions(obj, "max_blockers")]
    return min(caps) if caps else None


# -- Multi-block permissions (RULE 509.1b) -----------------------------------
#
# "~ can block an additional creature each combat."/"~ can block any number of
# creatures." widen a blocker's own capacity rather than narrow anything, but
# ride the same ``combat_restriction`` param-dict plumbing above since neither
# is a RULE 613 characteristic either. `blocking`/`additional_blocking` on
# `GameObject` hold, respectively, the first and every *subsequent* attacker a
# blocker is assigned to — a plain blocker only ever populates the first.


def blocking_attacker_ids(blocker: "GameObject") -> list[int]:
    """Every attacker ``blocker`` is currently blocking, in assignment order."""
    ids: list[int] = []
    if blocker.blocking is not None:
        ids.append(blocker.blocking)
    ids.extend(getattr(blocker, "additional_blocking", None) or [])
    return ids


def blocks_used(blocker: "GameObject") -> int:
    return len(blocking_attacker_ids(blocker))


def max_blocks_for(blocker: "GameObject") -> "Optional[int]":
    """How many attackers ``blocker`` may be assigned to block at once — 1 for
    an ordinary creature, higher (or unbounded) under a multi-block grant.
    ``None`` means no cap at all ("~ can block any number of creatures.",
    which wins outright over any stacked "additional creature" count).
    """
    if combat_restrictions(blocker, "unlimited_blocks"):
        return None
    extra = sum(int(e.get("count", 1)) for e in combat_restrictions(blocker, "extra_blocks"))
    return 1 + extra


def has_block_capacity(blocker: "GameObject") -> bool:
    """Whether ``blocker`` has room to be assigned to block one more attacker —
    the generalized sibling of the old bare ``blocker.blocking is None`` check,
    now that a multi-block grant can raise (or remove) the cap."""
    cap = max_blocks_for(blocker)
    return cap is None or blocks_used(blocker) < cap


def _quality_matches_type(quality: str, card: "Card") -> bool:
    """Whether a non-colour protection ``quality`` describes ``card``'s type.

    Handles the named-card-type qualities (`_CARD_TYPE_PROTECTIONS`, e.g.
    "protection from artifacts") and creature-type qualities ("protection
    from Dragons"/"Zombies"), matched against the subtypes after the type
    line's em dash with the quality's trailing plural "s" stripped.
    """
    attr = _CARD_TYPE_PROTECTIONS.get(quality)
    if attr is not None:
        return bool(getattr(card, attr, False))
    singular = quality[:-1] if quality.endswith("s") else quality
    if not singular:
        return False
    _, _, subtypes = card.type_line.lower().partition("—")
    return singular in subtypes


def is_protected_from(obj: "GameObject", source: "GameObject") -> bool:
    """Whether ``obj`` has protection that applies to ``source`` (RULE 702.16).

    Protection means ``source`` can't damage, enchant/equip/fortify, block
    (as a blocker of an attacker with this protection), or target ``obj`` —
    the "DEBT" rule; callers apply this predicate at each of those points.
    Covers a colour ``source`` shares, "creatures", named card types
    ("artifacts", "planeswalkers", …), creature types ("Dragons"), "all
    colors" (any coloured source), and "everything". Colour is read from the
    source's colour identity — the model's available proxy for a permanent's
    colour (RULE 105); good enough for the common mono/gold creatures, and it
    fails safe (no protection) when unknown. Reads ``obj.effective_oracle_
    text`` rather than ``obj.card.oracle_text`` directly, so a layer-3
    "text_change" static ability (RULE 612, e.g. Artificial Evolution's
    "protection from red" → "protection from blue") is honoured.
    """
    # Printed (+ layer-3-substituted) protections, plus any granted "until end
    # of turn" (Mother/Giver of Runes — `temp_protections`, RULE 702.16 as a
    # resolve-time grant rather than printed text), plus any *standing*
    # layer-6 grant (`granted_protections` — Hungry Lynx's "Cats you control
    # have protection from Rats", Flickering Ward's "Enchanted creature has
    # protection from the chosen color"; re-derived every `continuous.
    # recompute` pass, so it stops applying on its own when its source goes).
    quals = (
        protections_of_text(obj.effective_oracle_text)
        | frozenset(getattr(obj, "temp_protections", None) or set())
        | frozenset(getattr(obj, "granted_protections", None) or set())
    )
    if not quals:
        return False
    if "everything" in quals:
        return True
    # Effective colour (a layer-5 colour-changing effect if any, else the
    # printed identity) — the model's colour proxy (RULE 105).
    source_colors = set(getattr(source, "colors", None) or set())
    if "creatures" in quals and source.is_creature:
        return True
    if "all_colors" in quals and source_colors:
        return True
    # "Protection from colorless" (Giver of Runes) — a source with no colours.
    if "colorless" in quals and not source_colors:
        return True
    if quals & source_colors:
        return True
    source_card = getattr(source, "card", None)
    if source_card is not None:
        other_quals = quals - set(_COLOUR_WORDS.values()) - {"creatures", "all_colors", "everything"}
        if any(_quality_matches_type(q, source_card) for q in other_quals):
            return True
    return False


def _landwalk_slugs(obj: "GameObject") -> set[str]:
    """Every ``<type>walk`` keyword slug on ``obj``, from all its sources.

    Unions the card's Scryfall ``keywords`` list, a ``<type>walk`` clause in
    its oracle text, and any landwalk docked onto the object by the parser
    (`intrinsic_keywords`) or granted by a layer-6 static ability
    (`granted_keywords`). Landwalk is parametric (the land type is the
    parameter), so — unlike the flat combat keywords — it is tracked by the
    specific variant slug (``"islandwalk"``) rather than a bare flag.

    The oracle-text scan reads ``obj.effective_oracle_text`` rather than
    ``obj.card.oracle_text`` directly — the same RULE 612/layer-3 treatment
    `is_protected_from`'s `protections_of_text` call already gets, so a
    layer-3 "text_change" static ability (Artificial Evolution's "Islandwalk"
    → "Swampwalk"-shaped word substitution) is honoured here too, not just
    for protection.
    """
    slugs: set[str] = set()
    for kw in getattr(obj.card, "keywords", None) or []:
        slug = _normalize(str(kw))
        if slug.endswith("walk"):
            slugs.add(slug)
    text = (getattr(obj, "effective_oracle_text", "") or "").lower()
    for match in re.finditer(r"\b([a-z]+)walk\b", text):
        slugs.add(match.group(1) + "walk")
    for source in ("intrinsic_keywords", "granted_keywords"):
        for slug in getattr(obj, source, None) or set():
            if str(slug).endswith("walk"):
                slugs.add(str(slug))
    return slugs


def landwalk_subtypes(obj: "GameObject") -> frozenset[str]:
    """The basic land types ``obj`` has landwalk of (RULE 702.14), e.g. ``{"island"}``."""
    subs = {
        slug[:-4]
        for slug in _landwalk_slugs(obj)
        if len(slug) > 4 and slug[:-4] in _LAND_SUBTYPES
    }
    return frozenset(subs)


def unblockable_by_landwalk(
    attacker: "GameObject", defending_lands: "list[GameObject]"
) -> bool:
    """Whether ``attacker``'s landwalk makes it unblockable this combat (RULE 702.14b).

    True when the attacker has ``<type>walk`` and the defending player controls
    at least one land of that type — then no creature that player controls may
    block it (checked by the engine, which supplies the defender's lands).
    """
    subs = landwalk_subtypes(attacker)
    if not subs:
        return False
    for land in defending_lands:
        type_line = land.card.type_line.lower()
        if any(sub in type_line for sub in subs):
            return True
    return False


def can_block(attacker: "GameObject", blocker: "GameObject") -> bool:
    """Whether ``blocker`` is *able* to block ``attacker`` on evasion grounds.

    The keyword half of RULE 509.1b, on top of the engine's tap/control
    checks:

    * flying (702.9b): a creature with flying can be blocked only by a
      creature with flying or reach;
    * protection (702.16e): an attacker with protection from the blocker's
      quality can't be blocked by it;
    * shadow (702.28b/c), fear (702.36b), intimidate (702.13b), skulk
      (702.118b): the RULE 509.1b evasion family that reads the blocker's
      own characteristics (PAR-22).

    Menace is a *group* requirement (needs 2+ blockers) and so is enforced
    where the whole block is known, not here — see `min_blockers`.
    """
    if has_flying(attacker) and not (has_flying(blocker) or has_reach(blocker)):
        return False
    if is_protected_from(attacker, blocker):
        return False
    # RULE 702.28b/c Shadow — runs both ways: a shadow creature is blocked
    # only by shadow, and a non-shadow creature can't block one with shadow.
    if has_shadow(attacker) != has_shadow(blocker):
        return False
    # RULE 702.36b Fear — blocked only by artifact and/or black creatures.
    if has_fear(attacker) and not (
        _is_artifact(blocker) or "B" in _obj_colours(blocker)
    ):
        return False
    # RULE 702.13b Intimidate — blocked only by artifact creatures and/or
    # creatures that share a colour with the attacker.
    if has_intimidate(attacker) and not (
        _is_artifact(blocker) or (_obj_colours(blocker) & _obj_colours(attacker))
    ):
        return False
    # RULE 702.118b Skulk — can't be blocked by creatures with greater power.
    if has_skulk(attacker) and (blocker.power or 0) > (attacker.power or 0):
        return False
    return True


def lethal_damage(target: "GameObject", source: Optional["GameObject"]) -> int:
    """Damage from ``source`` that is lethal to ``target`` right now.

    Its remaining toughness normally; but any nonzero amount from a deathtouch
    source is lethal (RULE 702.2b / 510.1c-d "lethal damage" accounts for
    deathtouch), so trample only has to assign 1 past a deathtouch block.
    """
    remaining = max(0, (target.toughness or 0) - target.damage_marked)
    if source is not None and has_deathtouch(source):
        return min(1, remaining) if remaining > 0 else 0
    return remaining


def display_keywords(
    card: "Card",
    granted: "Optional[set[str]]" = None,
    removed: "Optional[set[str]]" = None,
    granted_protections: "Optional[set[str]]" = None,
) -> list[str]:
    """Human-facing keyword labels for the UI, e.g. ``["Flying", "Trample"]``.

    Ordered for a stable badge row; ``granted`` adds keyword slugs handed to
    the object by a layer-6 static ability (RULE 613.7f); ``removed``
    subtracts any a "loses <keyword>" static ability stripped (same layer,
    Colossus Hammer-shaped), mirroring `_obj_keywords`' precedence. "protection"
    is expanded to what it is from ("Protection: red") — printed qualities
    plus ``granted_protections``, a layer-6 *standing* protection grant
    (Hungry Lynx-shaped), which also puts the badge on a permanent whose
    printed text says nothing about protection at all. Reads the same
    recognition the engine uses so the board shows exactly what combat honours.
    """
    labels = {
        "flying": "Flying",
        "reach": "Reach",
        "first_strike": "First Strike",
        "double_strike": "Double Strike",
        "deathtouch": "Deathtouch",
        "trample": "Trample",
        "vigilance": "Vigilance",
        "lifelink": "Lifelink",
        "menace": "Menace",
        "defender": "Defender",
        "haste": "Haste",
        "indestructible": "Indestructible",
        # RULE 509.1b / 702.11b evasion & targeting keywords the engine now
        # enforces (PAR-22) — worth a badge so the board shows what combat
        # and targeting will honour.
        "shroud": "Shroud",
        "hexproof": "Hexproof",
        "fear": "Fear",
        "intimidate": "Intimidate",
        "skulk": "Skulk",
        "shadow": "Shadow",
    }
    kws = (keywords_of(card) | frozenset(granted or set())) - frozenset(removed or set())
    out = [label for slug, label in labels.items() if slug in kws]
    standing = frozenset(granted_protections or set())
    if "protection" in kws or standing:
        quals = sorted(protections_of(card) | standing)
        out.append("Protection: " + ", ".join(quals) if quals else "Protection")
    return out
