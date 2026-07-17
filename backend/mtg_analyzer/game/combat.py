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
from typing import TYPE_CHECKING, Optional

from ..parser.oracle.catalogue.levels import leveler_base_text

if TYPE_CHECKING:  # pragma: no cover - typing only, avoids a model→game cycle
    from ..models.card import Card
    from ..models.game_object import GameObject

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
    """
    is_leveler = bool(getattr(card, "is_leveler", False))
    raw_text = getattr(card, "oracle_text", "") or ""
    scan_text = leveler_base_text(raw_text) if is_leveler else raw_text

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
    return "menace" in _obj_keywords(obj)


def has_defender(obj: "GameObject") -> bool:
    return "defender" in _obj_keywords(obj)


def has_haste(obj: "GameObject") -> bool:
    return "haste" in _obj_keywords(obj)


def has_indestructible(obj: "GameObject") -> bool:
    return "indestructible" in _obj_keywords(obj)


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


def min_blockers(obj: "GameObject") -> int:
    """How many creatures must block ``obj`` for the block to be legal.

    2 for a menacing attacker (RULE 702.111b: "can't be blocked except by two
    or more creatures"), otherwise 1.
    """
    return 2 if has_menace(obj) else 1


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
    quals = protections_of_text(obj.effective_oracle_text)
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
    """
    slugs: set[str] = set()
    for kw in getattr(obj.card, "keywords", None) or []:
        slug = _normalize(str(kw))
        if slug.endswith("walk"):
            slugs.add(slug)
    text = (getattr(obj.card, "oracle_text", "") or "").lower()
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
      quality can't be blocked by it.

    Menace is a *group* requirement (needs 2+ blockers) and so is enforced
    where the whole block is known, not here — see `min_blockers`.
    """
    if has_flying(attacker) and not (has_flying(blocker) or has_reach(blocker)):
        return False
    if is_protected_from(attacker, blocker):
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
    card: "Card", granted: "Optional[set[str]]" = None, removed: "Optional[set[str]]" = None
) -> list[str]:
    """Human-facing keyword labels for the UI, e.g. ``["Flying", "Trample"]``.

    Ordered for a stable badge row; ``granted`` adds keyword slugs handed to
    the object by a layer-6 static ability (RULE 613.7f); ``removed``
    subtracts any a "loses <keyword>" static ability stripped (same layer,
    Colossus Hammer-shaped), mirroring `_obj_keywords`' precedence. "protection"
    is expanded to what it is from ("Protection: red"). Reads the same
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
    }
    kws = (keywords_of(card) | frozenset(granted or set())) - frozenset(removed or set())
    out = [label for slug, label in labels.items() if slug in kws]
    if "protection" in kws:
        quals = sorted(protections_of(card))
        out.append("Protection: " + ", ".join(quals) if quals else "Protection")
    return out
