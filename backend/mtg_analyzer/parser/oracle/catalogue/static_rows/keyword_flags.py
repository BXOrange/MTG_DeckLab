"""Static-ability helpers: keyword flags (split from `static_handlers` by PAR-172's method, ENG-59)."""

from __future__ import annotations

import re
from typing import Any, Optional
from ..keywords import KEYWORDS, KeywordShape, UNGRANTABLE_FLAG_KEYWORDS, keyword_slug, resolve_keyword
from ..subtype_vocabulary import SUBTYPES
from .anthem_patterns import COLOR_WORDS

#: "Ward—Pay 2 life." as a *quoted granted* keyword line (Hexing Squelcher's
#: "Other creatures you control have 'Ward—Pay 2 life.'") — RULE 702.21's
#: cost may be any clause (mana, life, sacrifice, discard, …), not just
#: mana, so the raw text is handed to `costs.parse_activation_cost`
#: downstream rather than re-parsed here.
GRANTED_WARD_RE = re.compile(r"^ward[\s—-]+(?P<cost>.+)$", re.IGNORECASE)

#: "Lands you control are every basic land type in addition to their other
#: types." (Dryad of the Ilysian Grove-shaped) — RULE 613.4a `add_
#: subtypes`, the fixed five-basic-type list.
LANDS_EVERY_BASIC_TYPE_RE = re.compile(
    r"^lands you control are every basic land type in addition to their other types$",
    re.IGNORECASE,
)
BASIC_LAND_TYPE_LIST: tuple[str, ...] = ("plains", "island", "swamp", "mountain", "forest")

#: "You may cast [noncreature/creature] spells as though they had flash."
#: (High Fae Trickster/Valley Floodcaller-shaped) — `continuous.has_
#: standing_flash_permission`'s own two scope flags.
FLASH_PERMISSION_RE = re.compile(
    r"^(?P<who>you|any player) may cast (?:(?P<filter>.+?) )?spells as though they had flash$",
    re.IGNORECASE,
)
#: PAR-226: the card-type words (and the two derived ones, "historic"/"colorless") a flash-permission filter may name
#: besides a subtype from the shared vocabulary; `continuous.has_standing_flash_permission` evaluates each as a union.
_FLASH_FILTER_TYPE_WORDS: frozenset[str] = frozenset({
    "artifact", "creature", "enchantment", "instant", "sorcery", "planeswalker", "legendary", "historic", "colorless",
    "familiar",
})
#: "legendary spells and artifact spells" / "aura and equipment spells": the union separators of a filter list.
_FLASH_FILTER_SPLIT_RE = re.compile(r" spells and | and |, (?:and )?")


def flash_permission_filter(text: Optional[str]) -> Optional[dict[str, Any]]:
    """The `flash_permission` filter params for the spell phrase in front of "spells" (``None`` = unrecognised).

    No phrase is every spell; "noncreature"/"creature" keep their flags; "<color> creature" is a colour-narrowed
    creature filter; otherwise a union of type words and subtypes (a word outside both vocabularies fails closed)."""
    if not text:
        return {}
    phrase = text.strip().lower()
    if phrase in ("noncreature", "creature"):
        return {f"{phrase}_only": True}
    color_creature = re.fullmatch(r"(white|blue|black|red|green) creature", phrase)
    if color_creature is not None:
        return {"creature_only": True, "color": COLOR_WORDS[color_creature.group(1)]}
    words = [w.strip() for w in _FLASH_FILTER_SPLIT_RE.split(phrase)]
    if not words or any(not w or " " in w for w in words):
        return None
    if not all(w in _FLASH_FILTER_TYPE_WORDS or w in SUBTYPES for w in words):
        return None
    return {"type_filter": words}

#: "Spells you control can't be countered." / "Creature spells you control
#: can't be countered." (Hexing Squelcher/Rionya, Sky Coyote-shaped) —
#: `GrantCantBeCounteredEffect`'s own two printed scopes.
GRANT_CANT_BE_COUNTERED_RE = re.compile(
    r"^(?:(?P<creature>creature )|(?P<subtype>[a-z]+) )?spells you control can'?t be countered$", re.IGNORECASE
)

#: "Your opponents can't search libraries." (Stranglehold-shaped).
GRANT_SEARCH_PROHIBITED_RE = re.compile(
    r"^your opponents can'?t search libraries$", re.IGNORECASE
)

#: "If an opponent would begin an extra turn, that player skips that turn
#: instead." (Stranglehold's own second clause). "a player" (unscoped —
#: still opponents-only per `GrantSkipExtraTurnsEffect`'s own single
#: printed shape) is the wider sibling seen on other real cards.
GRANT_SKIP_EXTRA_TURNS_RE = re.compile(
    r"^if an? (?:opponent|player) would begin an extra turn, that player "
    r"skips that turn instead$", re.IGNORECASE
)

#: The trailing sibling above's docstring deliberately left "…during your
#: turn." unclaimed generally (an "activate only during your turn" cost
#: restriction risk); this row is narrow enough to dodge that collision —
#: matched only when the *whole* clause is a bare keyword grant ending in
#: "during your turn" ("~ has first strike during your turn.", Razorkin
#: Needlehead-shaped), never an activation-cost sentence (those don't start
#: with "~ has"/"~ have").
DURING_YOUR_TURN_TRAILING_KEYWORD_RE = re.compile(
    r"^~ (?:has|have) (?P<inner>.+) during your turn$", re.IGNORECASE
)


def flag_keywords(text: str) -> Optional[list[str]]:
    """A "have <keywords>" list → grantable keyword slugs, or ``None`` if any
    isn't recognised (fail-closed — most other granted parametric keywords,
    e.g. "ward {2}", need behaviour the grant can't express yet).

    Almost every entry must be a parameterless FLAG keyword ("flying",
    "trample"). Two parametric exceptions: a landwalk variant ("forestwalk",
    "islandwalk", …) — RULE 702.14's land type lives in the slug itself, and
    `combat._landwalk_slugs` already matches any ``granted_keywords`` entry
    ending in "walk" directly, so the grant mechanism needs no separate
    quality param the way "protection from <color>" would — and a *bare*
    "hexproof" (RULE 702.11b's QUALITY shape, PAR-5, exists for the scoped
    "hexproof from <colour>" variant; unscoped "hexproof" is still its own
    complete keyword and grants exactly like a FLAG one). A bare "landwalk"
    with no type, or a real "hexproof from <colour>" scope (whose slug never
    resolves via `keyword_slug` to bare "hexproof"), still fails closed.
    """
    slugs: list[str] = []
    for part in re.split(r",|\band\b", text):
        part = part.strip()
        if not part:
            continue
        slug = keyword_slug(part)
        kdef = KEYWORDS.get(slug)
        if kdef is not None and kdef.slug in UNGRANTABLE_FLAG_KEYWORDS:
            return None
        if kdef is not None and (kdef.shape is KeywordShape.FLAG or kdef.slug == "hexproof"):
            slugs.append(kdef.slug)
            continue
        resolved = resolve_keyword(slug)
        if resolved is not None and resolved.slug == "landwalk" and slug != "landwalk":
            slugs.append(slug)
            continue
        return None
    return slugs or None


def flag_keywords_and_ward(text: str) -> Optional[tuple[list[str], Optional[str]]]:
    """`flag_keywords`'s sibling for callers whose own outer regex has
    widened its keyword-list character class to admit Ward's ``{cost}``
    (RULE 702.21b, PAR-65) — a keyword `flag_keywords` itself must keep
    rejecting, since a plain flag slug has nowhere to carry a cost param.
    Peels any "ward `<cost>`" entries out of the comma/and-joined list
    first (`GRANTED_WARD_RE`, the same pattern the quoted-ability-grant
    path already uses) and hands the rest to `flag_keywords` unchanged, so
    a list mixing Ward with ordinary flag keywords (Brotherhood Regalia's
    own "has ward {2}, is an assassin ..., and can't be blocked") still
    works. Two Wards in one list isn't a real card — fails closed rather
    than picking one. Returns ``(keywords, ward_cost)``; either half may be
    empty/``None`` but never both (an all-empty list is a caller error, not
    a "no grant" answer)."""
    ward_cost: Optional[str] = None
    plain_parts: list[str] = []
    for part in re.split(r",|\band\b", text):
        part = part.strip()
        if not part:
            continue
        ward = GRANTED_WARD_RE.fullmatch(part)
        if ward is not None:
            if ward_cost is not None:
                return None  # two Wards in one grant — not a real card
            ward_cost = ward.group("cost").strip()
            continue
        plain_parts.append(part)
    keywords: list[str] = []
    if plain_parts:
        resolved = flag_keywords(" and ".join(plain_parts))
        if resolved is None:
            return None
        keywords = resolved
    if not keywords and ward_cost is None:
        return None
    return (keywords, ward_cost)
