"""Parse a permanent's mana abilities (RULE 605), incl. dual-land choice.

Reference: docs/requirements/02_MVP_USECASES_REVISED.md R2.6 (Mana System).

A basic Forest taps for exactly `{G}`. A dual land ("{T}: Add {W} or
{U}.") taps for `{W}` *or* `{U}` — the player chooses one, they do NOT
get both (the bug this fixes: the old `_land_mana` added every colour a
land could make). So a card's tap-for-mana ability is modeled as a list
of mutually-exclusive *production options*, each a `{colour: count}`
dict; tapping picks one (index 0 when there's only one, so basics need no
prompt).

Beyond the printed options, a mana ability carries its own **cost**
(RULE 602.1) — almost always just `{T}`, but not always: Selvala, Heart of
the Wilds also charges `{G}`; Gnarlroot Trapper charges a life payment;
Birchlore Rangers/Heritage Druid tap *other* Elves instead of tapping
themselves at all. `parse_mana_abilities`/`mana_abilities_for` expose that
cost (an `ActivationCost`, `game/costs.py`) alongside the production
options so the engine actually charges it (`GameEngine.tap_for_mana`),
rather than assuming every mana ability's only cost is tapping its source.

Some mana abilities produce a *variable* amount — "Add {G} for each Elf you
control" (Elvish Archdruid), "equal to this creature's power" (Viridian
Joiner) — resolved against the battlefield at activation time
(`resolve_options`, given an optional `state`); with no `state` (a bare
`Card`/`GameObject` query, or a test not wired to a live game) the variable
count conservatively resolves to 1, same as the pre-existing (unscaled)
behaviour.

Parsing is intentionally simple — it covers basics, guildgates/duals,
tri-lands, "add one mana of any colour", "any combination of colours",
multi-pip lands (`{C}{C}`), and the "for each"/"equal to ... power"
variable-amount family — and approximates the long tail (filter lands)
rather than modeling every printed ability. RULE 605.1a excludes any
ability that requires a target from being a mana ability at all (Deathrite Shaman's
graveyard-exile abilities produce mana but target, so they're deliberately
never offered here — they belong on the stack like any other activated
ability, not through this fast no-stack path) — see `backend/ToDo_Backend.md`
for what's still open.

A "Exile this card from your hand: Add …" mana ability (Elvish/Simian
Spirit Guide) is never a *battlefield* one — `parse_mana_abilities`
excludes it, and its hand-zone counterpart `hand_mana_abilities`/
`hand_mana_abilities_for` picks it up instead
(`GameEngine.activate_hand_mana_ability`).

RULE 605.3a **mana spend restrictions** ("Spend this mana only to cast a
creature spell.") tag a `ManaAbility` with a ``restriction`` dict (see
`_parse_restriction`) recognizing the observed real-card shapes: casting a
creature/legendary/instant-or-sorcery/named-creature-type spell, casting
your commander, or paying a cost that itself contains ``{X}`` — several of
these also cover "... or activate an ability of a <same-type> source"
(Castle Garenbrig, Primal Beyond). A "spend this mana only" clause outside
that vocabulary (a land's own "of the chosen type"/"of that color", or a
mana-value-threshold clause) is left unrestricted — fail-soft like every
other unrecognized shape in this file, not a regression since the mana
still wasn't restriction-checked before this existed either. `ManaPool`
(`models/mana_pool.py`) itself stays ignorant of what a restriction
*means* — `restriction_predicate_for_cast`/`restriction_predicate_for_
activation` below build the actual predicate `ManaPool.can_pay`/`pay`
evaluate it with, from a spell/ability-source's printed characteristics.

"Add N mana **in any combination of colours**" (Flamebraider/Gwenna/
Smokebraider's fixed N=2, Selvala's variable N = the greatest power among
creatures you control) is a genuinely different shape from "any one
colour" above — the payer *splits* the total across colours instead of
picking a single colour repeated N times (`ManaAbility.any_combination`,
`validate_color_split`, `GameEngine.tap_for_mana`'s ``color_split``
parameter).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from ..parser.oracle.catalogue.levels import LEVEL_TIER_RE
from . import continuous
from .costs import ActivationCost, parse_activation_cost

#: Colours the five basic lands produce, by their basic land *type*.
BASIC_LAND_MANA = {
    "Plains": "W",
    "Island": "U",
    "Swamp": "B",
    "Mountain": "R",
    "Forest": "G",
}

#: The text inside an "Add …." clause (up to the sentence's period).
_ADD_CLAUSE_RE = re.compile(r"Add ([^.]*)\.")
_PIP_RE = re.compile(r"\{([WUBRGC])\}")
_ALTERNATIVE_SPLIT_RE = re.compile(r",| or ")
_ALL_COLORS = ("W", "U", "B", "R", "G")
#: Phrases meaning "the payer picks one colour" — either a fixed amount of it
#: ("one mana of any color", Elvish Harbinger) or a variable amount peeled off
#: by `_WHERE_X_RE` first ("X mana of any one color", Wirewood Channeler).
_ANY_COLOR_PHRASES = ("any color", "any colour", "any one color", "any one colour")

#: A fixed leading count on an "any colour" clause ("three mana of any one
#: color", Harold and Bob's granted ability) — this module works on *raw*
#: oracle text (no `normalize()` number-word folding), so a spelled-out
#: count needs its own small word map here. Absent/unrecognized → 1 (Elvish
#: Harbinger's bare "one mana of any color", and the "X mana of any one
#: color" variable-amount shape `_WHERE_X_RE` peels off *before* this ever
#: runs — its own base clause never has a real number to find here either).
_ANY_COLOR_COUNT_WORDS: dict[str, int] = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}
_ANY_COLOR_COUNT_RE = re.compile(
    r"^(?P<n>\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten)\s+mana\s+of\s+any",
    re.IGNORECASE,
)

#: A mana ability's own extra "You get N rad counters" side effect (RULE
#: 728/605.1a — Harold and Bob's granted "{T}: Add three mana of any one
#: color. You get two rad counters."), the rad-counter sibling of
#: `_SELF_DAMAGE_RE`. A spelled-out count needs the same local word map
#: `_ANY_COLOR_COUNT_WORDS` provides above (raw, non-normalized oracle text).
_SELF_RAD_COUNTERS_RE = re.compile(
    r"you get (?P<n>\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten) rad counters?",
    re.IGNORECASE,
)

#: RULE 605.1a: an ability that requires a target is never a mana ability,
#: however "mana-shaped" its effect looks (Deathrite Shaman's "Exile target
#: land card from a graveyard. Add one mana of any color." is a normal,
#: stack-using, responds-to-able activated ability, not a mana ability).
_TARGET_RE = re.compile(r"\btarget\b", re.IGNORECASE)

#: A mana ability's own extra "this creature/land deals N damage to you"
#: side effect (RULE 605.1a permits a mana ability other effects besides
#: producing mana) — the painland/Elves-of-Deep-Shadow template.
_SELF_DAMAGE_RE = re.compile(
    r"(?:this creature|this land|this permanent|~) deals (\d+) damage to you",
    re.IGNORECASE,
)

#: "<base> for each <subject>" (Elvish Archdruid, Circle of Dreams Druid,
#: Priest of Titania, Gyre Sage).
_FOR_EACH_RE = re.compile(r"^(?P<base>.*?)\s+for each\s+(?P<subject>.+?)$", re.IGNORECASE)
#: "an amount of <base> equal to <who>'s power" (Marwyn, Viridian Joiner).
_EQUAL_TO_POWER_RE = re.compile(
    r"^an amount of\s+(?P<base>.*?)\s+equal to\s+(?P<who>.+?)'s power$", re.IGNORECASE
)
#: "X mana of any one color, where X is the number of <subject>" (Wirewood
#: Channeler) — captures the (still-variable) base clause and the subject
#: separately, since the base itself needs `_parse_clause`'s any-colour path.
_WHERE_X_RE = re.compile(
    r"^(?P<base>x mana of any one colou?r),\s*where x is the number of\s+(?P<subject>.+?)$",
    re.IGNORECASE,
)
_SUBJECT_CONTROL_RE = re.compile(r"^(?P<noun>.+?)\s+you control$", re.IGNORECASE)
_SUBJECT_BATTLEFIELD_RE = re.compile(r"^(?P<noun>.+?)\s+on the battlefield$", re.IGNORECASE)
_SUBJECT_COUNTER_RE = re.compile(
    r"^(?P<kind>[+\-]?\d+/[+\-]?\d+) counters? on (?:this creature|~)$", re.IGNORECASE
)

# --- RULE 605.3a mana spend restrictions ("Spend this mana only ...") ----

#: The whole restriction sentence's own clause, captured separately from the
#: "Add ..." clause since they're two sentences on the same cost line.
_RESTRICTION_CLAUSE_RE = re.compile(r"spend this mana only (?:to|on)\s+(?P<clause>.+?)\.", re.IGNORECASE)
#: RULE 601.2c's "and that spell can't be countered" rider, printed on some
#: of these (Cavern of Souls, Delighted Halfling) — stripped before
#: classifying the clause below; the "can't be countered" half isn't a
#: spend restriction at all and isn't modeled here (a resolve-time
#: property of the cast spell, not the mana that paid for it).
_CANT_BE_COUNTERED_TAIL_RE = re.compile(r",\s*and that spell can'?t be countered$", re.IGNORECASE)
#: "... or activate an ability of a(n) <source>" / "... or activate
#: abilities of <source>(s)" — peeled off the end of a clause (Castle
#: Garenbrig, Primal Beyond); the exact trailing source word isn't
#: re-verified against the clause's own type (fail-soft: every real card
#: found pairs them, so this is a simplification, not a guess).
_RESTRICTION_ABILITY_TAIL_RE = re.compile(
    r"^(?P<head>.+?)\s+or activate (?:an ability of an?|abilities of)\s+.+$", re.IGNORECASE
)
_RESTRICTION_CONTAINS_X_RE = re.compile(r"^costs that contain \{x\}$", re.IGNORECASE)
_RESTRICTION_CREATURE_SPELL_RE = re.compile(r"^cast (?:an? )?creature spells?$", re.IGNORECASE)
_RESTRICTION_COMMANDER_RE = re.compile(r"^cast your commander$", re.IGNORECASE)
_RESTRICTION_LEGENDARY_RE = re.compile(r"^cast (?:an? )?legendary spell$", re.IGNORECASE)
_RESTRICTION_INSTANT_SORCERY_RE = re.compile(
    r"^cast (?:an? )?instant (?:and|or) sorcery spells?$", re.IGNORECASE
)
#: "cast a <Type1> or <Type2> spell" (Turtle Lair) — checked before the
#: single-type form below since it also matches "cast (?:an? )?[a-z]+".
_RESTRICTION_MULTI_TYPE_RE = re.compile(
    r"^cast (?:an? )?(?P<t1>[a-z]+) or (?P<t2>[a-z]+) spells?$", re.IGNORECASE
)
#: "cast a(n) <Type> spell" / "cast a(n) <Type> creature spell" (Flamebraider's
#: "Elemental", Gnarlroot Trapper's "Elf creature") — a single named
#: creature type, the optional literal "creature" just along for the ride.
_RESTRICTION_TYPE_RE = re.compile(
    r"^cast (?:an? )?(?P<type>[a-z]+)(?: creature)? spells?$", re.IGNORECASE
)

# --- "any combination of colours" (a *split*, not a single-colour choice) --

#: Spelled-out amount words, as printed on the "any combination" cards
#: (Flamebraider/Gwenna/Smokebraider's fixed "two"; Selvala's "X").
_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}
#: "<amount> mana in any combination of colours[, where X is <subject>]" —
#: a genuinely different shape from "any one colour"/`_ANY_COLOR_PHRASES`
#: above: the payer splits the total across colours instead of picking one
#: colour repeated (see `ManaAbility.any_combination`).
_COMBINATION_CLAUSE_RE = re.compile(
    r"^(?P<amount>[a-z]+) mana in any combination of colou?rs"
    r"(?:,\s*where\s+x\s+is\s+(?P<subject>.+))?$",
    re.IGNORECASE,
)
#: Selvala, Heart of the Wilds' variable-amount subject — the only
#: "where X is ..." subject observed on a combination-of-colours ability.
_GREATEST_POWER_CONTROL_RE = re.compile(
    r"^the greatest power among creatures you control$", re.IGNORECASE
)


def _parse_combination_selector(raw_clause: str) -> Optional[dict[str, Any]]:
    """"<amount> mana in any combination of colours[, where X is <subject>]"
    (Flamebraider/Gwenna/Smokebraider's fixed "two"; Selvala's variable "X")
    → an `amount_selector`-shaped dict consumed by `_resolve_amount`'s
    ``"literal"``/``"greatest_power_control"`` kinds, or ``None`` when
    ``raw_clause`` isn't this shape at all, or is but names an unrecognised
    ``X`` subject (fail-soft, same convention as the rest of this module —
    the caller then falls through to the ordinary non-combination parse
    path, same as before this shape existed)."""
    m = _COMBINATION_CLAUSE_RE.match(raw_clause.strip())
    if m is None:
        return None
    amount_word = m.group("amount").lower()
    if amount_word == "x":
        subject = m.group("subject")
        if subject is not None and _GREATEST_POWER_CONTROL_RE.match(subject.strip()):
            return {"kind": "greatest_power_control"}
        return None
    n = _NUMBER_WORDS.get(amount_word)
    return {"kind": "literal", "n": n} if n is not None else None


def _singularize(word: str) -> str:
    """A plural creature type → singular ("elves"→"elf", "goblins"→"goblin")."""
    if word.endswith("ves"):
        return word[:-3] + "f"
    if word.endswith("s"):
        return word[:-1]
    return word


@dataclass
class ManaAbility:
    """One parsed "<cost>: Add …" line (or a granted/basic-land equivalent).

    ``options`` are the *base* (unscaled) mutually-exclusive production
    choices — already resolved for a fixed-amount ability, or the per-colour
    ``{c: 1}`` base a variable one scales from `amount_selector`.
    ``self_damage`` is a mana ability's own "deals N damage to you" rider
    (Elves of Deep Shadow), applied when the ability is activated.

    ``min_level``/``max_level`` gate a Leveler's (RULE 711) own mana
    ability to whichever ``LEVEL n-m``/``n+`` tier printed it — ``None``/
    ``None`` (the default, and the only case for a non-Leveler card) means
    unconditional. Mirrors `game/continuous.py`'s static-effect Leveler
    gate (same field names, same "as long as this object's own level
    counter is in range" condition, RULE 613.6), just applied to a mana
    ability instead of a `StaticAbility` — see `mana_abilities_for`.

    ``restriction`` (RULE 605.3a, ``None`` — no restriction — by default)
    is the parsed "Spend this mana only ..." clause, tagged onto the mana
    this ability produces (`GameEngine.tap_for_mana`) so `ManaPool` only
    lets it pay a cost `restriction_predicate_for_cast`/`_for_activation`
    says it may.

    ``any_combination`` (``False`` by default) marks an "add N mana in any
    combination of colours" ability (Flamebraider/Gwenna/Smokebraider's
    fixed N=2, Selvala's variable N) — a genuinely different shape from
    "any one colour" above: the payer *splits* the resolved total across
    colours instead of picking a single colour repeated N times.
    ``options`` still holds the same per-colour "N of that one colour"
    menu as an any-one-colour ability (so a caller ignoring the split
    still gets a legal, if inflexible, single-colour default via
    ``option_index``) — `GameEngine.tap_for_mana`'s ``color_split``
    parameter is what actually lets a caller distribute the total instead.
    """

    cost: ActivationCost = field(default_factory=ActivationCost)
    options: list[dict[str, int]] = field(default_factory=list)
    amount_selector: Optional[dict[str, Any]] = None
    self_damage: int = 0
    #: A mana ability's own "You get N rad counters" rider (RULE 728,
    #: Harold and Bob's granted quoted ability — "{T}: Add three mana of
    #: any one color. You get two rad counters.") — the same "applied right
    #: alongside mana production, no stack" shape as ``self_damage``, just
    #: a different rider effect. Hand-authored only (`game/ability_
    #: catalogue.py`); no oracle-text grammar recognizes this compound
    #: mana-ability-plus-rider shape yet.
    self_rad_counters: int = 0
    min_level: Optional[int] = None
    max_level: Optional[int] = None
    restriction: Optional[dict[str, Any]] = None
    any_combination: bool = False


def _selector_from_subject(subject: str) -> Optional[dict[str, Any]]:
    """RULE 605.1a-adjacent "for each <subject>" → a count selector dict, or
    ``None`` for a subject shape outside the small recognised vocabulary
    (fail-soft: the caller then leaves the amount unscaled, same as before
    this grammar existed)."""
    subject = subject.strip().rstrip(".")
    m = _SUBJECT_COUNTER_RE.match(subject)
    if m is not None:
        return {"kind": "counters_on_self", "counter": m.group("kind").lower()}
    m = _SUBJECT_CONTROL_RE.match(subject)
    if m is not None:
        noun = _singularize(m.group("noun").strip().lower())
        return {"kind": "count", "scope": "control", "subtype": None if noun == "creature" else noun}
    m = _SUBJECT_BATTLEFIELD_RE.match(subject)
    if m is not None:
        noun = _singularize(m.group("noun").strip().lower())
        return {"kind": "count", "scope": "battlefield", "subtype": None if noun == "creature" else noun}
    return None


def _self_name_forms(card_name: Optional[str]) -> set:
    name = (card_name or "").strip()
    forms = {name.lower()} if name else set()
    if "," in name:
        forms.add(name.split(",")[0].strip().lower())
    if "//" in name:
        forms.add(name.split("//")[0].strip().lower())
    return forms


def _power_selector(who: str, card_name: Optional[str]) -> Optional[dict[str, Any]]:
    who = who.strip().lower()
    if who in ("this creature", "~") or who in _self_name_forms(card_name):
        return {"kind": "power_of_self"}
    return None


def _peel_amount_selector(clause: str, card_name: Optional[str]) -> tuple[str, Optional[dict[str, Any]]]:
    """Split a variable "Add …" clause into its base (still-parseable)
    production clause and an `amount_selector`, or return ``clause``
    unchanged with no selector when it isn't one of the recognised variable
    shapes (including a "for each"/"equal to" subject this grammar doesn't
    recognise — fail-soft, not fail-closed: the base clause still parses to
    whatever fixed amount it names, exactly the pre-existing behaviour)."""
    m = _WHERE_X_RE.match(clause)
    if m is not None:
        selector = _selector_from_subject(m.group("subject"))
        if selector is not None:
            return m.group("base"), selector
    m = _EQUAL_TO_POWER_RE.match(clause)
    if m is not None:
        selector = _power_selector(m.group("who"), card_name)
        if selector is not None:
            return m.group("base"), selector
    m = _FOR_EACH_RE.match(clause)
    if m is not None:
        selector = _selector_from_subject(m.group("subject"))
        if selector is not None:
            return m.group("base"), selector
    return clause, None


def _parse_restriction(effect_text: str) -> Optional[dict[str, Any]]:
    """A "Spend this mana only ..." clause (RULE 605.3a) in ``effect_text``
    as a restriction dict, or ``None`` when there's no such clause at all
    *or* it's outside the recognised vocabulary (fail-soft — the "Add ..."
    production still parses either way, just unrestricted; see the module
    docstring for exactly which shapes this covers)."""
    m = _RESTRICTION_CLAUSE_RE.search(effect_text)
    if m is None:
        return None
    clause = _CANT_BE_COUNTERED_TAIL_RE.sub("", m.group("clause").strip())
    allow_ability = False
    tail = _RESTRICTION_ABILITY_TAIL_RE.match(clause)
    if tail is not None:
        clause, allow_ability = tail.group("head"), True

    if _RESTRICTION_CONTAINS_X_RE.match(clause):
        return {"kind": "contains_x"}
    if _RESTRICTION_CREATURE_SPELL_RE.match(clause):
        return {"kind": "creature_spell", "allow_ability": allow_ability}
    if _RESTRICTION_COMMANDER_RE.match(clause):
        return {"kind": "commander_spell"}
    if _RESTRICTION_LEGENDARY_RE.match(clause):
        return {"kind": "legendary_spell"}
    if _RESTRICTION_INSTANT_SORCERY_RE.match(clause):
        return {"kind": "instant_or_sorcery_spell"}
    m = _RESTRICTION_MULTI_TYPE_RE.match(clause)
    if m is not None:
        return {
            "kind": "type_spell",
            "types": [m.group("t1").lower(), m.group("t2").lower()],
            "allow_ability": allow_ability,
        }
    m = _RESTRICTION_TYPE_RE.match(clause)
    if m is not None:
        return {"kind": "type_spell", "types": [m.group("type").lower()], "allow_ability": allow_ability}
    return None


def _restriction_allows_cast(restriction: dict[str, Any], obj: Any, has_x: bool) -> bool:
    kind = restriction.get("kind")
    if kind == "contains_x":
        return has_x
    card = getattr(obj, "card", obj)
    if kind == "creature_spell":
        return bool(getattr(card, "is_creature", False))
    if kind == "type_spell":
        return any(continuous.has_subtype(obj, t) for t in restriction.get("types", ()))
    if kind == "legendary_spell":
        return bool(getattr(card, "is_legendary", False))
    if kind == "commander_spell":
        return bool(getattr(obj, "is_commander", False))
    if kind == "instant_or_sorcery_spell":
        return bool(getattr(card, "is_instant", False) or getattr(card, "is_sorcery", False))
    return False  # unrecognised restriction kind — fail closed, never usable


def restriction_predicate_for_cast(obj: Any, has_x: bool = False) -> Callable[[dict], bool]:
    """An ``allows_restriction`` predicate (`ManaPool.can_pay`/`pay`) for
    casting ``obj`` — whether a restricted mana lot (RULE 605.3a) may pay
    for *this* spell. ``has_x`` is whether the cost actually being paid
    contains an unresolved ``{X}`` (`ManaCost.has_variable` stays ``True``
    post-`with_x`, see `models/mana_cost.py`) — only the ``contains_x``
    restriction kind consults it.
    """
    return lambda restriction: _restriction_allows_cast(restriction, obj, has_x)


def _restriction_allows_activation(restriction: dict[str, Any], source: Any, has_x: bool) -> bool:
    kind = restriction.get("kind")
    if kind == "contains_x":
        return has_x
    # legendary_spell/commander_spell/instant_or_sorcery_spell only ever
    # gate *casting a spell* (RULE 605.3a's printed text never pairs them
    # with "or activate an ability of ...") — no observed card needs them
    # here, so they simply never authorize paying an ability's cost.
    if not restriction.get("allow_ability"):
        return False
    if kind == "creature_spell":
        return bool(getattr(source, "is_creature", False))
    if kind == "type_spell":
        return any(continuous.has_subtype(source, t) for t in restriction.get("types", ()))
    return False


def restriction_predicate_for_activation(source: Any, has_x: bool = False) -> Callable[[dict], bool]:
    """``restriction_predicate_for_cast``'s counterpart for activating an
    ability on ``source`` (RULE 605.3a's "... or activate an ability of a
    creature") — only a restriction explicitly recognised as covering
    ability activation (``allow_ability``) or ``contains_x`` ever applies."""
    return lambda restriction: _restriction_allows_activation(restriction, source, has_x)


def mana_options(card: Any) -> list[dict[str, int]]:
    """Mutually-exclusive ways a card taps for mana (empty if it can't).

    Returns e.g. ``[{"G": 1}]`` for a Forest, ``[{"W": 1}, {"U": 1}]`` for
    a WU dual, ``[{"C": 2}]`` for an Eldrazi land, or one option per colour
    for "add one mana of any colour". The first option is the default the
    goldfish auto-player / a single-option tap uses. A thin flattening view
    over `parse_mana_abilities` — see that for cost/variable-amount detail.
    """
    options: list[dict[str, int]] = []
    for ability in parse_mana_abilities(card):
        options.extend(ability.options)
    return _dedupe(options)


def _parse_mana_ability_lines(
    text: str, name: Optional[str], want_hand_exile: bool = False
) -> list[ManaAbility]:
    """`ManaAbility`s from each ``<cost>: Add …`` line in ``text`` — the
    line-based core `parse_mana_abilities`/`hand_mana_abilities` and
    `parse_mana_abilities`' Leveler block-splitting both funnel through, so
    a card with more than one line doesn't have one line's cost bleed into
    another's production. RULE 605.1a's "no target" requirement is enforced
    per line — a line whose effect mentions "target" is skipped entirely
    (never a mana ability, whatever it produces).

    ``want_hand_exile`` selects *which* lines: ``False`` (the default,
    `parse_mana_abilities`' battlefield tap-for-mana path) keeps only lines
    whose cost is *not* "Exile this card from your hand" (Elvish/Simian
    Spirit Guide — never activatable from the battlefield, since it's a
    hand-zone-only cost, not a target of `GameEngine.tap_for_mana` at all);
    ``True`` (`hand_mana_abilities`) inverts that, keeping only the
    hand-exile lines.
    """
    abilities: list[ManaAbility] = []
    for line in text.split("\n"):
        line = line.strip()
        if '"' in line:
            # A granted-ability description quoted inside another line
            # ("Each creature you control with a counter on it has '{T}:
            # Add {G}.'", Rishkar) — that ability belongs to whatever it's
            # granted to, not this card itself (RULE 613.7f grants are
            # hand-authored in `game/ability_catalogue.py`, not auto-parsed
            # here); skip so it doesn't get mis-attributed as this card's
            # own mana ability.
            continue
        cost_text, sep, effect_text = line.partition(":")
        if not sep:
            continue
        effect_text = effect_text.strip()
        add_match = _ADD_CLAUSE_RE.search(effect_text)
        if add_match is None:
            continue
        if _TARGET_RE.search(effect_text) or _TARGET_RE.search(cost_text):
            continue  # RULE 605.1a — a targeted ability is never a mana ability
        cost = parse_activation_cost(cost_text)
        if cost.exile_self_from_hand != want_hand_exile:
            continue
        rad_match = _SELF_RAD_COUNTERS_RE.search(effect_text)
        combination_selector = _parse_combination_selector(add_match.group(1))
        if combination_selector is not None:
            damage_match = _SELF_DAMAGE_RE.search(effect_text)
            abilities.append(ManaAbility(
                cost=cost,
                options=[{color: 1} for color in _ALL_COLORS],
                amount_selector=combination_selector,
                any_combination=True,
                self_damage=int(damage_match.group(1)) if damage_match else 0,
                self_rad_counters=_rad_count_of(rad_match) if rad_match else 0,
                restriction=_parse_restriction(effect_text),
            ))
            continue
        base_clause, selector = _peel_amount_selector(add_match.group(1), name)
        options = _dedupe(_parse_clause(base_clause))
        if not options:
            continue
        damage_match = _SELF_DAMAGE_RE.search(effect_text)
        abilities.append(ManaAbility(
            cost=cost,
            options=options,
            amount_selector=selector,
            self_damage=int(damage_match.group(1)) if damage_match else 0,
            self_rad_counters=_rad_count_of(rad_match) if rad_match else 0,
            restriction=_parse_restriction(effect_text),
        ))
    return abilities


#: A Leveler tier header ("LEVEL 1-4"/"LEVEL 5+"), matched case-insensitively
#: against *raw* (non-normalized) oracle text — `_parse_mana_ability_lines`
#: needs the original casing (``_ADD_CLAUSE_RE`` etc. are case-sensitive),
#: unlike `parser/oracle/catalogue/levels.split_leveler_blocks`, which only
#: ever sees already-lowercased `normalize()` output.
_LEVEL_TIER_RAW_RE = re.compile(LEVEL_TIER_RE.pattern, re.IGNORECASE)


def _split_leveler_blocks_raw(text: str) -> tuple[list[str], list[tuple[int, Optional[int], list[str]]]]:
    """`levels.split_leveler_blocks`, but on raw (mixed-case) oracle text."""
    preamble: list[str] = []
    blocks: list[tuple[int, Optional[int], list[str]]] = []
    current: Optional[tuple[int, Optional[int], list[str]]] = None
    for line in text.split("\n"):
        match = _LEVEL_TIER_RAW_RE.match(line.strip())
        if match is not None:
            if current is not None:
                blocks.append(current)
            lo = int(match.group("lo"))
            hi = None if match.group("plus") else int(match.group("hi"))
            current = (lo, hi, [])
        elif current is not None:
            current[2].append(line)
        else:
            preamble.append(line)
    if current is not None:
        blocks.append(current)
    return preamble, blocks


def parse_mana_abilities(card: Any) -> list[ManaAbility]:
    """Every mana ability (RULE 605) `card` prints, cost and production both.

    Line-based: each ``<cost>: Add …`` line becomes its own `ManaAbility`.
    A basic land's colour comes from its type line, not oracle text, so it
    gets a synthetic ``{T}``-only ability instead.

    A Leveler (RULE 711.4c, ``card.is_leveler``) has its own mana ability
    (if any) nested inside a specific ``LEVEL n-m``/``n+`` tier — e.g.
    Joraga Treespeaker's "{T}: Add {G}{G}." only while ``LEVEL 1-4``'s
    counter range holds; at level 0 (before levelling up at all) or level 5+
    it has none of its own printed there (level 5+ instead *grants* the
    ability to Elves, an unrelated layer-6 static effect, already gated).
    Each block is parsed on its own body text and tagged with that tier's
    ``min_level``/``max_level`` (`mana_abilities_for` filters by them); any
    preamble text before the first tier (rare, but not disallowed) stays
    unconditional, same as a non-Leveler card.
    """
    basic = _basic_options(card)
    if basic:
        return [ManaAbility(cost=ActivationCost(taps_self=True), options=basic)]

    name = getattr(card, "name", None)
    raw_text = getattr(card, "oracle_text", "") or ""

    if getattr(card, "is_leveler", False):
        preamble_lines, blocks = _split_leveler_blocks_raw(raw_text)
        abilities = _parse_mana_ability_lines("\n".join(preamble_lines), name)
        for lo, hi, body_lines in blocks:
            for ability in _parse_mana_ability_lines("\n".join(body_lines), name):
                ability.min_level = lo
                ability.max_level = hi
                abilities.append(ability)
        return abilities

    return _parse_mana_ability_lines(raw_text, name)


def _leveler_tier_active(obj: Any, ability: ManaAbility) -> bool:
    """Whether ``obj``'s own ``level`` counter is within ``ability``'s
    Leveler tier (RULE 711.4c) — unconditionally ``True`` for a non-Leveler
    ability (``min_level``/``max_level`` both ``None``). Mirrors
    `game/continuous.py`'s identical static-effect gate."""
    if ability.min_level is None and ability.max_level is None:
        return True
    n = obj.counters.get("level", 0) if hasattr(obj, "counters") else 0
    if ability.min_level is not None and n < ability.min_level:
        return False
    if ability.max_level is not None and n > ability.max_level:
        return False
    return True


def mana_abilities_for(obj: Any, state: Optional[Any] = None) -> list[ManaAbility]:
    """`parse_mana_abilities` for a `GameObject`, folding in layer-6 grants
    (RULE 613.7f — "Elves you control have '{T}: Add {B}.'") as plain
    ``{T}``-only abilities, and resolving each one's `amount_selector`
    against ``state`` (``None`` leaves a variable amount at its
    conservative 1x default). A Leveler's own tier-gated mana ability
    (`_leveler_tier_active`) is included only while ``obj``'s current
    ``level`` counter is in that tier's range — e.g. Joraga Treespeaker's
    "{T}: Add {G}{G}." offers nothing at level 0 (before levelling up) or
    level 5+ (that tier grants the ability to Elves instead, a separate
    layer-6 static effect, not this card's own — already gated correctly)."""
    printed = [
        ManaAbility(
            cost=ability.cost,
            options=resolve_options(ability, obj, state),
            amount_selector=None,
            self_damage=ability.self_damage,
            self_rad_counters=ability.self_rad_counters,
            restriction=ability.restriction,
            any_combination=ability.any_combination,
        )
        for ability in parse_mana_abilities(obj.card)
        if _leveler_tier_active(obj, ability)
    ]
    granted = [
        ManaAbility(cost=ActivationCost(taps_self=True), options=[dict(opt)])
        for opt in getattr(obj, "granted_mana_options", [])
    ]
    return printed + granted


def hand_mana_abilities(card: Any) -> list[ManaAbility]:
    """RULE 605.1a "Exile this card from your hand: Add …" mana abilities
    (Elvish Spirit Guide, Simian Spirit Guide) — `parse_mana_abilities`'
    hand-zone counterpart, since a card printing only this line is never a
    *battlefield* tap-for-mana source at all (`parse_mana_abilities`
    deliberately excludes it). Not Leveler-block-aware (no observed real
    card pairs the two shapes) and never granted by a layer-6 static
    effect (that grant machinery only ever targets battlefield
    permanents) — both simplifications, same fail-soft convention as the
    rest of this module."""
    name = getattr(card, "name", None)
    raw_text = getattr(card, "oracle_text", "") or ""
    return _parse_mana_ability_lines(raw_text, name, want_hand_exile=True)


def hand_mana_abilities_for(obj: Any, state: Optional[Any] = None) -> list[ManaAbility]:
    """`hand_mana_abilities` for a `GameObject` sitting in a player's hand,
    resolving each one's `amount_selector` against ``state`` the same way
    `mana_abilities_for` does for a battlefield permanent (no observed real
    card needs it — every hand-exile ability prints a fixed amount — kept
    for shape parity rather than special-cased away)."""
    return [
        ManaAbility(
            cost=ability.cost,
            options=resolve_options(ability, obj, state),
            amount_selector=None,
            self_damage=ability.self_damage,
            self_rad_counters=ability.self_rad_counters,
            restriction=ability.restriction,
            any_combination=ability.any_combination,
        )
        for ability in hand_mana_abilities(obj.card)
    ]


def resolve_options(ability: ManaAbility, obj: Any, state: Optional[Any] = None) -> list[dict[str, int]]:
    """``ability.options`` scaled by its `amount_selector` (if any) against
    ``obj``/``state`` — e.g. Elvish Archdruid's ``{"G": 1}`` base becomes
    ``{"G": 4}`` with four Elves on the battlefield."""
    if ability.amount_selector is None:
        return [dict(opt) for opt in ability.options]
    n = _resolve_amount(ability.amount_selector, obj, state)
    return [{color: count * n for color, count in opt.items()} for opt in ability.options]


def _resolve_amount(selector: dict[str, Any], obj: Any, state: Optional[Any]) -> int:
    kind = selector["kind"]
    if kind == "literal":
        return selector["n"]
    if kind == "greatest_power_control":
        if state is None:
            return 1  # no battlefield to check power against — conservative default
        battlefield = getattr(state, "battlefield", None) or []
        controller = getattr(obj, "controller_id", None)
        powers = [
            getattr(o, "power", 0) or 0
            for o in battlefield
            if getattr(o, "controller_id", None) == controller and getattr(o, "is_creature", False)
        ]
        return max(powers) if powers else 0
    if kind == "power_of_self":
        return max(0, getattr(obj, "power", 0) or 0)
    if kind == "counters_on_self":
        counters = getattr(obj, "counters", None) or {}
        return counters.get(selector["counter"], 0)
    if kind == "count":
        if state is None:
            return 1  # no battlefield to count against — conservative default
        battlefield = getattr(state, "battlefield", None) or []
        subtype = selector.get("subtype")
        if selector["scope"] == "control":
            controller = getattr(obj, "controller_id", None)
            pool = [o for o in battlefield if getattr(o, "controller_id", None) == controller]
        else:
            pool = list(battlefield)
        if subtype is None:
            return sum(1 for o in pool if getattr(o, "is_creature", False))
        return sum(1 for o in pool if continuous.has_subtype(o, subtype))
    return 1


def mana_options_for(obj: Any, state: Optional[Any] = None) -> list[dict[str, int]]:
    """``mana_options`` for a `GameObject`, folding in layer-6 grants and
    resolving variable amounts against ``state`` when given. Duck-typed: any
    object with ``.card``, ``.controller_id`` and ``.granted_mana_options``
    works, so tests can pass a bare stub.
    """
    options: list[dict[str, int]] = []
    for ability in mana_abilities_for(obj, state):
        options.extend(ability.options)
    return _dedupe(options)


def _basic_options(card: Any) -> list[dict[str, int]]:
    type_line = getattr(card, "type_line", "") or ""
    name = getattr(card, "name", "") or ""
    produced: list[dict[str, int]] = []
    for basic_name, color in BASIC_LAND_MANA.items():
        # A basic land *type* (or the exact basic name) grants that colour.
        if basic_name in type_line or name == basic_name:
            produced.append({color: 1})
    return produced


def _rad_count_of(match: "re.Match[str]") -> int:
    """A captured `_SELF_RAD_COUNTERS_RE` token → its int value."""
    token = match.group("n").lower()
    return int(token) if token.isdigit() else _ANY_COLOR_COUNT_WORDS.get(token, 1)


def _parse_clause(clause: str) -> list[dict[str, int]]:
    lowered = clause.lower()
    if any(phrase in lowered for phrase in _ANY_COLOR_PHRASES):
        # "one mana of any colour" / "three mana of any one colour" / "X
        # mana of any one colour" — one single-colour option each (the
        # payer picks the colour), scaled by any *fixed* leading count
        # (the "X"/variable case has already been peeled off by
        # `_peel_amount_selector` before this runs, so its own base clause
        # never matches `_ANY_COLOR_COUNT_RE` and safely falls back to 1).
        count_match = _ANY_COLOR_COUNT_RE.match(clause.strip())
        amount = 1
        if count_match:
            token = count_match.group("n").lower()
            amount = int(token) if token.isdigit() else _ANY_COLOR_COUNT_WORDS.get(token, 1)
        return [{color: amount} for color in _ALL_COLORS]

    options: list[dict[str, int]] = []
    for alternative in _ALTERNATIVE_SPLIT_RE.split(clause):
        pips = _PIP_RE.findall(alternative)
        if not pips:
            continue
        counts: dict[str, int] = {}
        for pip in pips:
            counts[pip] = counts.get(pip, 0) + 1
        options.append(counts)
    return options


def _dedupe(options: list[dict[str, int]]) -> list[dict[str, int]]:
    seen: set[tuple] = set()
    unique: list[dict[str, int]] = []
    for option in options:
        key = tuple(sorted(option.items()))
        if key not in seen:
            seen.add(key)
            unique.append(option)
    return unique


def validate_color_split(split: dict[str, int], total: int) -> dict[str, int]:
    """A player's chosen colour distribution for an "any combination of
    colours" mana ability (`ManaAbility.any_combination`) — every key must
    be a real WUBRG colour (no printed "any combination" ability produces
    colourless), every value a non-negative int, and the values must sum to
    exactly ``total`` (the ability's resolved amount, e.g. Selvala's X).
    Raises ``ValueError`` otherwise; `GameEngine.tap_for_mana` surfaces that
    as an illegal action, same as any other invalid choice. Zero-count
    colours are dropped from the returned dict (so it composes cleanly with
    `ManaPool.add_many`)."""
    cleaned: dict[str, int] = {}
    for color, count in split.items():
        if color not in _ALL_COLORS:
            raise ValueError(f"invalid mana colour in combination split: {color!r}")
        count = int(count)
        if count < 0:
            raise ValueError(f"invalid mana amount in combination split: {count!r}")
        if count:
            cleaned[color] = count
    if sum(cleaned.values()) != total:
        raise ValueError(f"combination split must total {total}, got {sum(cleaned.values())}")
    return cleaned


def option_label(option: dict[str, int]) -> str:
    """A short glyph label for a production option, e.g. "🟢" or "⟡⟡"."""
    glyph = {"W": "⚪", "U": "🔵", "B": "⚫", "R": "🔴", "G": "🟢", "C": "⟡"}
    parts: list[str] = []
    for color in ("C", "W", "U", "B", "R", "G"):
        parts.append(glyph[color] * option.get(color, 0))
    return "".join(parts) or "—"
