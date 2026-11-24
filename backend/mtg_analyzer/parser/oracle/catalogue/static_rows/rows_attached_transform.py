"""Aura transformations of the host: "Enchanted land is a Swamp." and "Enchanted creature loses all abilities and is
a blue Frog creature with base power and toughness 1/1." (PAR-289).

Each is a standing static of the Aura (RULE 303.4 / 611.3b), so it stops when the Aura leaves or the host changes. The
change is split by layer the way RULE 613 requires and every piece already exists in the engine:

* layer 4 `type_change` -- ``set_land_types`` (RULE 305.7: a basic land type also strips the land's rules text) or
  ``set_types`` + ``set_creature_types`` (RULE 205.1a / 205.3m);
* layer 5 `color_change` with ``set=True`` (RULE 105.3: "is a blue ..." replaces the colours);
* layer 6 `remove_all_abilities` (RULE 613.7f) and `grant_keyword`;
* layer 7b `pt_set` (RULE 613.4b: "base power and toughness").

PAR-289 M2 adds the rest of the "enchanted <permanent> is ..." family (the A3 shapes): a creature-type statement with
a base P/T ("Enchanted creature is a Turtle with base power and toughness 0/1."), the card-type replacement
("Enchanted permanent is an enchantment and loses all other card types.", RULE 205.1a), the colourless
type-plus-ability Auras ("... is a colorless Food artifact with "..." and loses all other abilities") and the
supertype grant ("Enchanted permanent is legendary.", RULE 205.4a), plus the self-statement "~ has flying and is a
Knight in addition to its other types".

Pure regex + data; no ``game/`` imports.
"""

from __future__ import annotations

import re
from typing import Optional

from .....models.cards.creature_types import CREATURE_SUBTYPES
from .....models.cards.subtype_types import SUBTYPES_BY_CARD_TYPE
from ...spec import EffectSpec
from ..subgrammars import COLOR_LETTERS
from .cost_patterns import BASIC_LAND_WORDS
from .granted_abilities import quoted_ability_grant_effects_list, type_addition_params
from .keyword_flags import flag_keywords, flag_keywords_and_ward
from .matcher_types import DECLINE, StaticContext, StaticResult

_ATTACHED = {"affects": "attached_permanent"}
#: RULE 305.6: the five basic land types, singular (the Aura text never pluralises them).
_BASIC_LAND_TYPE_ALT = "plains|island|swamp|mountain|forest"
_LAND_IS_BASIC_RE = re.compile(
    rf"enchanted land is (?:an? )?(?P<types>(?:{_BASIC_LAND_TYPE_ALT})(?:, (?:{_BASIC_LAND_TYPE_ALT}))*(?:,? and (?:{_BASIC_LAND_TYPE_ALT}))?)"
)
_LAND_IS_CHOSEN_RE = re.compile(r"enchanted land is the chosen type\.?")
_BASE_PT = r"with base power and toughness (?P<p2>\d+)/(?P<t2>\d+)"
_LOSES_THEN_RE = re.compile(
    r"enchanted creature loses all abilities and "
    rf"(?:has base power and toughness (?P<p>\d+)/(?P<t>\d+)|is (?:an? )?(?P<words>[a-z ]+?)(?: {_BASE_PT})?)"
)
_IS_THEN_LOSES_RE = re.compile(
    rf"enchanted creature is (?:an? )?(?P<words>[a-z ]+?) {_BASE_PT} and loses all abilities"
)
#: Stasis Field: the base P/T and a keyword are granted by the same Aura, so only the *other* abilities go.
_BASE_KEYWORD_LOSES_RE = re.compile(
    r"enchanted creature has base power and toughness (?P<p>\d+)/(?P<t>\d+), has (?P<kw>[a-z ]+), "
    r"and loses all other abilities"
)


def type_words(words: str) -> Optional[tuple[list[str], list[str], list[str]]]:
    """``(colour letters, card types, creature types)`` of "[<colours>] <creature types> [creature]", else ``None``.

    Only creature words: an unknown word is never guessed to be a type (fail closed), and "colorless" is not offered
    because this row has no printed example of it."""
    tokens = words.split()
    colors: list[str] = []
    while tokens and tokens[0] in COLOR_LETTERS and tokens[0] != "colorless":
        colors.append(COLOR_LETTERS[tokens.pop(0)])
    types: list[str] = []
    if tokens and tokens[-1] == "creature":
        types.append(tokens.pop())
    if not tokens or any(t not in CREATURE_SUBTYPES for t in tokens):
        return None
    return colors, types, ["-".join(p.capitalize() for p in t.split("-")) for t in tokens]


def _transform_specs(
    words: Optional[str], power: Optional[str], toughness: Optional[str], *, loses: bool
) -> Optional[list[EffectSpec]]:
    specs: list[EffectSpec] = []
    if loses:
        specs.append(EffectSpec("remove_all_abilities", dict(_ATTACHED)))
    if words is not None:
        parsed = type_words(words)
        if parsed is None:
            return None
        colors, types, subtypes = parsed
        # RULE 205.1a: a stated card type replaces the card types; RULE 205.3m: creature types always replace.
        specs.append(EffectSpec("type_change", {
            **_ATTACHED, **({"set_types": types} if types else {}), "set_creature_types": subtypes}))
        if colors:
            specs.append(EffectSpec("color_change", {**_ATTACHED, "colors": colors, "set": True}))
    if power is not None:
        specs.append(EffectSpec("pt_set", {**_ATTACHED, "power": int(power), "toughness": int(toughness)}))
    return specs or None


def static_attached_land_basic_type(ctx: StaticContext) -> StaticResult:
    if _LAND_IS_CHOSEN_RE.fullmatch(ctx.text):
        # RULE 305.7 + 613.1d: the Aura's "as ~ enters, choose a basic land type" answer, read live off the Aura.
        return [EffectSpec("type_change", {**_ATTACHED, "set_land_types_from_source": True})]
    m = _LAND_IS_BASIC_RE.fullmatch(ctx.text)
    if m is None:
        return None
    names = [BASIC_LAND_WORDS[w] for w in re.findall(_BASIC_LAND_TYPE_ALT, m.group("types"))]
    return [EffectSpec("type_change", {**_ATTACHED, "set_land_types": names})]


def static_attached_loses_abilities_transform(ctx: StaticContext) -> StaticResult:
    m = _LOSES_THEN_RE.fullmatch(ctx.text)
    if m is not None:
        power = m.group("p") or m.group("p2")
        toughness = m.group("t") or m.group("t2")
        specs = _transform_specs(m.group("words"), power, toughness, loses=True)
        return DECLINE if specs is None else specs
    m = _IS_THEN_LOSES_RE.fullmatch(ctx.text)
    if m is not None:
        # RULE 613.7: the ability removal is its own layer-6 effect whatever order the sentence prints it in.
        specs = _transform_specs(m.group("words"), m.group("p2"), m.group("t2"), loses=True)
        return DECLINE if specs is None else specs
    m = _BASE_KEYWORD_LOSES_RE.fullmatch(ctx.text)
    if m is not None:
        resolved = flag_keywords_and_ward(m.group("kw"))
        if resolved is None or resolved[1] or not resolved[0]:
            return DECLINE
        # The removal is stamped first so the keyword this same Aura grants survives it (RULE 613.7: timestamp order
        # inside layer 6); "all other abilities" is exactly "all but what this effect grants".
        base = _transform_specs(None, m.group("p"), m.group("t"), loses=True)
        assert base is not None
        return [base[0], EffectSpec("grant_keyword", {**_ATTACHED, "keywords": resolved[0]}), *base[1:]]
    return None


# -- A3: "enchanted <permanent> is ..." statements --------------------------------------------------------------------

_CREATURE_TYPES_IS_RE = re.compile(
    rf"enchanted creature is (?:an? )?(?P<words>[a-z]+(?: [a-z]+)*?)(?: {_BASE_PT})?"
)
#: RULE 205.1a: the card types a "becomes ..." statement can name for a permanent, with their subtype tables.
_SET_CARD_TYPES = ("artifact", "enchantment", "land", "creature")
_SET_TYPES_RE = re.compile(
    r"enchanted permanent is (?:an? )?(?P<colorless>colorless )?(?P<words>[a-z]+(?: [a-z]+)*?)"
    r'(?: with "(?P<inner>[^"]+)")?'
    r"(?:,? and (?:it )?loses all other (?P<loses>card types and abilities|card types|abilities))?"
)
_LEGENDARY_RE = re.compile(r"enchanted permanent is legendary")


def static_attached_creature_types(ctx: StaticContext) -> StaticResult:
    m = _CREATURE_TYPES_IS_RE.fullmatch(ctx.text)
    if m is None:
        return None
    # Only creature-type words (a bare colour or "creature" alone is a different statement); fail closed otherwise.
    if m.group("words") == "creature" or type_words(m.group("words")) is None:
        return None
    specs = _transform_specs(m.group("words"), m.group("p2"), m.group("t2"), loses=False)
    return None if specs is None else specs


def _set_types_words(words: str) -> Optional[tuple[list[str], list[str]]]:
    """``(card types, subtypes)`` of "<subtypes> <card type>" or ``None``: every subtype must belong to a card type the
    sentence names (RULE 205.3), and at least one card type is required."""
    tokens = words.split()
    types = [t for t in tokens if t in _SET_CARD_TYPES]
    rest = [t for t in tokens if t not in _SET_CARD_TYPES]
    if not types:
        return None
    if any(not any(t in SUBTYPES_BY_CARD_TYPE[ct] for ct in types) for t in rest):
        return None
    return types, ["-".join(p.capitalize() for p in t.split("-")) for t in rest]


def static_attached_permanent_is(ctx: StaticContext) -> StaticResult:
    if _LEGENDARY_RE.fullmatch(ctx.text):
        return [EffectSpec("type_change", {**_ATTACHED, "legendary": True})]  # RULE 205.4a
    m = _SET_TYPES_RE.fullmatch(ctx.text)
    if m is None:
        return None
    parsed = _set_types_words(m.group("words"))
    if parsed is None:
        return None
    types, subtypes = parsed
    quoted = None
    if m.group("inner"):
        # The printed comma after a quoted ability ("... of any color,\" and it loses ...") sits inside the quotes.
        quoted = quoted_ability_grant_effects_list(m.group("inner").rstrip(","))
        if quoted is None:
            return None
    loses = m.group("loses") or ""
    specs: list[EffectSpec] = []
    # RULE 613.7: the removal is its own layer-6 effect stamped before the ability this same Aura grants.
    if "abilities" in loses:
        specs.append(EffectSpec("remove_all_abilities", dict(_ATTACHED)))
    # RULE 205.1a: the stated card types replace the permanent's card types; a stated subtype replaces its subtypes.
    specs.append(EffectSpec("type_change", {
        **_ATTACHED, "set_types": types, **({"set_subtypes": subtypes} if subtypes else {})}))
    if m.group("colorless"):
        specs.append(EffectSpec("color_change", {**_ATTACHED, "colors": [], "set": True}))  # RULE 105.2c
    specs.extend(quoted or [])
    return specs


# -- self statement "~ has <keywords> and is a <type> in addition to its other types" -----------------------------------

_SELF_TYPE_ADDITION_RE = re.compile(
    r"~ (?:has (?P<kw>[a-z][a-z, ]*?) and )?is an? (?P<words>[a-z]+(?: [a-z]+)*?) in addition to its other types"
)


def static_self_type_addition(ctx: StaticContext) -> StaticResult:
    m = _SELF_TYPE_ADDITION_RE.fullmatch(ctx.text)
    if m is None:
        return None
    type_params = type_addition_params(m.group("words"))
    if type_params is None:
        return None
    specs: list[EffectSpec] = []
    if m.group("kw"):
        keywords = flag_keywords(m.group("kw"))
        if keywords is None:
            return None
        specs.append(EffectSpec("grant_keyword", {"affects": "self", "keywords": keywords}))
    specs.append(EffectSpec("type_change", {"affects": "self", **type_params}))  # RULE 205.1b / 613.1d
    return specs
