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
tri-lands, "add one mana of any colour", multi-pip lands (`{C}{C}`), and the
"for each"/"equal to ... power" variable-amount family — and approximates
the long tail (filter lands, mana *spend* restrictions like "spend this
mana only to cast a creature spell", "any combination of colours") rather
than modeling every printed ability. RULE 605.1a excludes any ability that
requires a target from being a mana ability at all (Deathrite Shaman's
graveyard-exile abilities produce mana but target, so they're deliberately
never offered here — they belong on the stack like any other activated
ability, not through this fast no-stack path) — see `backend/ToDo_Backend.md`
for what's still open.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

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
    """

    cost: ActivationCost = field(default_factory=ActivationCost)
    options: list[dict[str, int]] = field(default_factory=list)
    amount_selector: Optional[dict[str, Any]] = None
    self_damage: int = 0
    min_level: Optional[int] = None
    max_level: Optional[int] = None


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


def _parse_mana_ability_lines(text: str, name: Optional[str]) -> list[ManaAbility]:
    """`ManaAbility`s from each ``<cost>: Add …`` line in ``text`` — the
    line-based core `parse_mana_abilities` and its Leveler block-splitting
    both funnel through, so a card with more than one line doesn't have one
    line's cost bleed into another's production. RULE 605.1a's "no target"
    requirement is enforced per line — a line whose effect mentions "target"
    is skipped entirely (never a mana ability, whatever it produces).
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
        if cost.exile_self_from_hand:
            continue  # not activatable from the battlefield at all (Elvish Spirit Guide)
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
        )
        for ability in parse_mana_abilities(obj.card)
        if _leveler_tier_active(obj, ability)
    ]
    granted = [
        ManaAbility(cost=ActivationCost(taps_self=True), options=[dict(opt)])
        for opt in getattr(obj, "granted_mana_options", [])
    ]
    return printed + granted


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


def _parse_clause(clause: str) -> list[dict[str, int]]:
    lowered = clause.lower()
    if any(phrase in lowered for phrase in _ANY_COLOR_PHRASES):
        # "one mana of any colour" / "X mana of any one colour" — one
        # single-colour option each (the payer picks the colour).
        return [{color: 1} for color in _ALL_COLORS]

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


def option_label(option: dict[str, int]) -> str:
    """A short glyph label for a production option, e.g. "🟢" or "⟡⟡"."""
    glyph = {"W": "⚪", "U": "🔵", "B": "⚫", "R": "🔴", "G": "🟢", "C": "⟡"}
    parts: list[str] = []
    for color in ("C", "W", "U", "B", "R", "G"):
        parts.append(glyph[color] * option.get(color, 0))
    return "".join(parts) or "—"
