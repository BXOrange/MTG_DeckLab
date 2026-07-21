"""Static continuous-ability handlers — anthems and keyword grants (docs/09).

Reference: docs/concepts/09_ORACLE_EFFECT_PARSER.md (effect-family handlers), RULE 613
(the layer system these feed). A *permanent's* standing sentence like "Other
creatures you control get +1/+1" or "Goblins you control have haste" is a
**static** ability, not a one-shot effect — it reshapes other permanents
continuously while its source is in play. This module recognises those two
families and emits `EffectSpec`s the binder turns into `StaticAbility`s
(`anthem` → layer 7c, `grant_keyword` → layer 6), with a tribal **subtype**
filter for lords (Goblin King, Lord of Atlantis).

Only creature scopes are claimed — "creatures you control", a plural creature
type ("goblins you control"), or "<type> creatures you control" — with a small
block-list keeping non-creature scopes ("artifacts you control …") from being
mis-read as anthems (fail-closed). Anything with an "until end of turn" tail is
a *temporary* effect an instant grants, not a static ability, and won't
full-match here.

A second, closed family recognises an Aura/Equipment/Fortification's own
attached-permanent buff — "equipped creature gets +2/+2", "enchanted creature
has trample" (RULE 303.4/301.5, docs/11 §6 "attached_permanent"). Unlike the
"you control" scopes above, these five printed subject phrases
(`_ATTACHED_SUBJECTS`) always resolve off the ability's own source's
`attached_to`, so they emit `affects="attached_permanent"` rather than any
controller-scoped selector; `game/continuous.py`'s `group_selector_objects`
already honours that selector for both `anthem` and `grant_keyword` (it's the
same code path the hand-authored Armadillo Cloak entry in
`game/ability_catalogue.py` uses) — only the parser recognition was missing.

A third family (Card-pool Batch 7) recognises RULE 601.2b's "as ~ enters,
choose a creature type/color" (`enter_choice_specs`, a sibling entry point
segmenter.py calls separately since it wraps as an ``enter_replacement``
`AbilitySpec`, not ``static``) plus the "… of the chosen type/color …"
dynamic tail on the anthem/grant families above (`_CHOSEN_TAIL`) and "~ is
the chosen type in addition to its other types" (`_IS_CHOSEN_TYPE_RE`) — see
`game/continuous.py`'s ``subtype_from_source``/``color_from_source``/
``add_subtypes_from_source`` params for how the layer engine reads the
choice back.

A fourth family (Card-pool Batch 8) recognises three "permission" statics
that aren't about a permanent's own characteristics at all: "you may play an
additional land on each of your turns" (`extra_land_drop`), "you have no
maximum hand size" (`no_max_hand_size`), and "you may choose not to untap ~
during your untap step" (`no_untap_optional`) — all consulted by
per-*player*/per-*object* helpers in `game/continuous.py` rather than the
RULE 613 layer engine proper (the same treatment `cast_limit`/`draw_limit`/
`no_untap` already got).

Pure regex + data — **no `game/` imports** (front-end security boundary).
"""

from __future__ import annotations

import re
from typing import NamedTuple, Optional

from ..spec import EffectSpec, ParserProvenance
from .handlers import ONCE_PER_TURN_MARKER, SORCERY_SPEED_MARKER
from .keywords import KEYWORDS, KeywordShape, keyword_slug, resolve_keyword
from .subgrammars import CANT_BE_COUNTERED_RE, COUNT, count_of

#: Trigger events a granted triggered ability can be safely re-scoped to a
#: *different* object each time it's granted (`continuous.
#: _granted_trigger_condition` matches by the event's own subject key —
#: ``instance_id`` for the RULE 603.1 object-subject four, ``source_id`` for
#: ``DAMAGE`` — see `continuous._GRANTED_EVENT_KEYS`). Deliberately excludes
#: any phase/upkeep event (``STEP_BEGIN`` — "at the beginning of your
#: upkeep" is a pre-existing controller-scoping gap for even a top-level
#: card's own printed ability, `segmenter.py`'s ``_PHASE_TRIGGER_RE``
#: docstring).
_GRANTABLE_TRIGGER_EVENTS = frozenset({"ENTERS_BATTLEFIELD", "DIES", "ATTACKS", "BLOCKS", "DAMAGE"})

#: Type words that are *not* creature subtypes — a scope built on one of these
#: isn't a creature anthem/grant, so we don't claim it.
_NONCREATURE_TYPES: frozenset[str] = frozenset(
    {"creature", "artifact", "enchantment", "land", "permanent", "planeswalker", "token"}
)

#: Colour words → their WUBRG/C symbol, for a colour-scoped anthem.
_COLOR_WORDS: dict[str, str] = {
    "white": "W", "blue": "U", "black": "B", "red": "R", "green": "G", "colorless": "C",
}

#: An optional "of the chosen type/color" tail (RULE 601.2b, Adaptive
#: Automaton/Ward Sliver-shaped) — the dynamic sibling of a literal subtype/
#: colour scope, sitting between the "you control" clause and "get"/"have".
_CHOSEN_TAIL = r"(?: of the chosen (?P<chosen>type|color))?"

# "[Other] <scope> [you control] [of the chosen type/color] get +N/+N [and
# have <keywords>]"  (anthem, +grant)
_ANTHEM_RE = re.compile(
    r"(?:(?P<scope>other) )?(?P<body>[a-z][a-z ]*?)(?P<yours> you control)?"
    rf"{_CHOSEN_TAIL} "
    r"get (?P<p>[+-]\d+)/(?P<t>[+-]\d+)"
    r"(?: and have (?P<kw>[a-z][a-z, ]*))?",
    re.IGNORECASE,
)
# "[Other] <scope> [you control] [of the chosen type/color] have <keywords>"
# (keyword grant, layer 6)
_GRANT_RE = re.compile(
    r"(?:(?P<scope>other) )?(?P<body>[a-z][a-z ]*?)(?P<yours> you control)?"
    rf"{_CHOSEN_TAIL} "
    r"have (?P<kw>[a-z][a-z, ]*)",
    re.IGNORECASE,
)
# "[Other] <scope> [you control] [of the chosen type/color] have \"<ability>\""
# (Tyvar Kell/Acidic Sliver-shaped — "Elves you control have '{T}: Add
# {B}.'"/"All Slivers have '{2}, Sacrifice this permanent: ...'") — the
# non-attached sibling of `_ATTACHED_QUOTED_GRANT_RE`/`_ATTACHED_QUOTED_
# ANTHEM_GRANT_RE` above: a group-scoped grant of a *full* ability
# (recursively parsed via `_quoted_ability_grant_effects`, same as the
# attached family) rather than a bare keyword list (`_GRANT_RE` just
# above). Shares `_scope`/`_scope_params` with `_GRANT_RE`/`_ANTHEM_RE` for
# the `affects` (+ subtype/colour/tokens/chosen) params.
_QUOTED_GRANT_RE = re.compile(
    r"(?:(?P<scope>other) )?(?P<body>[a-z][a-z ]*?)(?P<yours> you control)?"
    rf"{_CHOSEN_TAIL} "
    r'have "(?P<inner>.+)"',
    re.IGNORECASE | re.DOTALL,
)

#: Card-type words the "opponent-scoped"/"prohibition"/"type-overwrite"
#: families below recognise as a `card_type` selector (`continuous.
#: _has_card_type` reads the matching `Card.is_<word>` flag) — deliberately
#: small: only the categories that actually appear in this shape on real
#: cards (a spell-only type like "instant" never does, since none of these
#: clauses talk about spells).
_CARD_TYPE_WORDS: frozenset[str] = frozenset(
    {"artifact", "creature", "enchantment", "land", "planeswalker", "permanent"}
)

# "Activated abilities of <type>[s] can't be activated."  (RULE 602 prohibition,
# Collector Ouphe/Stony Silence/Null Rod) — global, not "you control"-scoped:
# it silences *every* qualifying permanent's activated abilities, including
# the prohibiting permanent's own if it itself qualifies (Null Rod is an
# Artifact and its printed text carries no self-exemption).
_ACTIVATION_PROHIBITION_RE = re.compile(
    r"activated abilities of (?P<word>[a-z]+) can'?t be activated", re.IGNORECASE
)

# "<Type> spells cost {N} more/less to cast."  (RULE 601.2f tax/discount,
# Thalia/Thorn of Amethyst/Vryn Wingmare-shaped) — unlike "Spells you cast
# cost {N} less" (self-scoped, already covered by the hand-authored
# `cost_reduction` shape), the bare "<type> spells cost …" phrasing with no
# "you cast"/"your opponents cast" qualifier taxes *everyone*, the caster's
# own controller included.
_SPELL_TYPE_WORDS: frozenset[str] = frozenset(
    {"noncreature", "creature", "artifact", "instant", "sorcery", "enchantment", "planeswalker"}
)
_SPELL_COST_TAX_RE = re.compile(
    r"(?:(?P<word>[a-z]+) )?spells cost \{(?P<n>\d+)\} (?P<dir>more|less) to cast", re.IGNORECASE
)

# "Each player can't cast more than N spell(s) each turn."  (RULE 601-area
# prohibition, Eidolon of Rhetoric/Rule of Law/Archon of Emeria) — a flat,
# unscoped per-player-per-turn cast cap; ``normalize`` already folds a
# spelled-out "one" to "1" before this ever runs.
_CAST_LIMIT_RE = re.compile(
    r"each player can'?t cast more than (?P<n>\d+) spells? each turn", re.IGNORECASE
)

# "You may play [an|N] additional land[s] on/during each of your/their
# turns."  (RULE 305.2 permission static, Exploration/Dryad of the Ilysian
# Grove/Azusa-shaped) or its unscoped "Each player may play …" sibling
# (Rites of Flourishing/Storm Cauldron) — `_EXTRA_LAND_DROP_RE.group("n")`
# via `count_of` handles both "an"/"a" and a digit count (Azusa's "two
# additional lands"→"2" after `normalize`'s spelled-out-number fold). The
# one-turn "…this turn" phrasing (Explore-shaped) is a different, resolve-
# time-effect shape claimed by `catalogue.handlers`' `extra_land_play` row
# instead, not this static family.
_EXTRA_LAND_DROP_RE = re.compile(
    rf"(?P<subject>you|each player) may play {COUNT} additional lands? "
    r"(?:on|during) each of (?:your|their) turns",
    re.IGNORECASE,
)

# "You have no maximum hand size."  (RULE 402.2, A-Wizard Class/Body of
# Knowledge-shaped) or "Players have no maximum hand size." (Anvil of
# Bogardan/Folio of Fancies, unscoped). The durational "…for the rest of the
# game"/"…until your next turn" one-shot variants (Enter the Infinite/
# Choice of Fortunes-shaped) don't fullmatch this — they're a different,
# resolve-time-granted shape, deliberately left unclaimed.
_NO_MAX_HAND_SIZE_RE = re.compile(
    r"(?P<subject>you have|players have) no maximum hand size", re.IGNORECASE
)

# "You may choose not to untap ~ during your untap step."  (RULE 502.1
# self-scoped opt-out, Rubinia Soulsinger/Hivis of the Scale/The Pandorica-
# shaped) — `~` covers all three printed subject wordings ("this creature"/
# "this artifact"/"this land", folded by `normalize._fold_self_reference`)
# uniformly. Unlike `_NO_UNTAP_RE` below (an unconditional restriction), this
# only *permits* skipping untap — actually skipping it needs the controller
# to separately toggle `GameObject.skip_untap` on (`GameEngine.
# set_skip_untap`). Deliberately excludes every targeted/imposed "doesn't
# untap … for as long as this remains tapped" variant (Sand Squid/Ice Floe-
# shaped) — a different family entirely (an activated ability locking a
# *different* permanent), not "you may choose" at all.
_NO_UNTAP_OPTIONAL_RE = re.compile(
    r"you may choose not to untap ~ during your untap step", re.IGNORECASE
)

# "You gain life rather than lose life from radiation."  (RULE 728.1a,
# Strong, the Brutish Thespian) — a per-player permission static redirecting
# a ``cause="radiation"`` life loss into a gain instead
# (`continuous.has_radiation_life_gain`, `RulesEngine.lose_life`). No
# "players gain..." unscoped variant exists in the real card pool yet, so
# unlike `_NO_MAX_HAND_SIZE_RE` this has no ``subject`` alternation.
_RADIATION_LIFE_GAIN_RE = re.compile(
    r"you gain life rather than lose life from radiation", re.IGNORECASE
)

# "~ doesn't untap during your untap step."  (RULE 502.3-adjacent
# self-restriction, Basalt Monolith/Grim Monolith/Mana Vault) — `~` is the
# self-reference token `normalize._fold_self_reference`/`_fold_self_name`
# folds "this artifact"/the card's own printed name to (Card-pool Batch 1),
# so this must match the folded form, not the literal "this <type>" text
# that normalize never leaves in place.
_NO_UNTAP_RE = re.compile(
    r"~ doesn'?t untap during your untap step", re.IGNORECASE
)

# "Creatures entering don't cause abilities to trigger."  (RULE 603
# prohibition, Tocatli Honor Guard/Hushwing Gryff/Torpor Orb) — global: it
# silences *every* triggered ability (including the entering creature's own)
# that would otherwise fire off a matching battlefield-entry event, for as
# long as this static is in play, regardless of whose creature it is.
_TRIGGER_PROHIBITION_RE = re.compile(
    r"(?P<word>[a-z]+) entering don'?t cause abilities to trigger", re.IGNORECASE
)

# "[Nonbasic] <type>[s] [and <type>[s]] your opponents control enter
# tapped."  (RULE 614.1, board-wide — Manglehorn/Dauntless Dismantler's
# "artifacts", Archon of Emeria's "nonbasic lands", Blind Obedience's
# "artifacts and creatures") — distinct from `ability_catalogue.
# enters_tapped` (a card's own printed tapped-entry clause about *itself*):
# this is a standing effect from a *different* permanent, scoped to "your
# opponents" and optionally narrowed to nonbasic. ``words`` may name two
# card types joined by "and" (Blind Obedience), emitting one spec per type.
_OPPONENTS_ENTER_TAPPED_RE = re.compile(
    r"(?:(?P<nonbasic>nonbasic) )?(?P<words>[a-z]+(?: and [a-z]+)?) your opponents control enter tapped",
    re.IGNORECASE,
)

# "[Nonbasic] <type>[s] [and <type>[s]] enter tapped."  (RULE 614.1,
# board-wide, Root Maze-shaped) — the *unscoped* sibling of
# `_OPPONENTS_ENTER_TAPPED_RE`: no "your opponents control" qualifier at
# all, so it applies to every player's matching permanents, including the
# static's own controller's.
_ALL_ENTER_TAPPED_RE = re.compile(
    r"(?:(?P<nonbasic>nonbasic) )?(?P<words>[a-z]+(?: and [a-z]+)?) enter tapped",
    re.IGNORECASE,
)

#: WUBRG basic-land-type word → the mana colour it taps for (RULE 305.6) —
#: a small local copy of `game/mana_abilities.BASIC_LAND_MANA`'s data (the
#: front-end can't import `game/`, and it's five literal pairs, not worth a
#: shared-data indirection).
_BASIC_LAND_COLOR: dict[str, str] = {
    "plains": "W", "island": "U", "swamp": "B", "mountain": "R", "forest": "G",
}
#: Singular/plural basic-land-type word → its canonical (capitalised) name.
_BASIC_LAND_WORDS: dict[str, str] = {}
for _name in _BASIC_LAND_COLOR:
    _BASIC_LAND_WORDS[_name] = _name.capitalize()
    _BASIC_LAND_WORDS[_name + "s"] = _name.capitalize()
del _name

# "Nonbasic lands are <BasicType>."  (RULE 613.5 full layer-4 type overwrite,
# board-wide — Magus of the Moon/Blood Moon) — unlike `type_change`'s ordinary
# "are also creatures" shape (which only *adds* a type), this *replaces* the
# land's subtypes outright (RULE 613.5's "loses all other types") and grants
# the corresponding basic land's mana ability (RULE 305.6), so the clause
# emits two specs together: a `type_change` carrying `set_subtypes`, and a
# `grant_mana_ability` for the matching colour.
_TYPE_OVERWRITE_RE = re.compile(r"nonbasic lands are (?P<word>[a-z]+)", re.IGNORECASE)

# "~ can be your commander."  (RULE 903.3 deck-legality permission,
# Jeska/Tevesh Szat-shaped) — a plain-text line with **no in-game behavioral
# effect** (nothing about the battlefield/stack/turn structure changes), so
# unlike every family above this claims the line and emits *nothing* at all —
# the same "claim it, contribute no spec" treatment RULE 614.1 tapped-entry/
# entry-counter clauses get in `gate._process_line`. A generic self-reference
# match (``~``, folded from the card's own name by `normalize`), not
# hardcoded to any one card name.
_COMMANDER_ELIGIBLE_RE = re.compile(r"~ can be your commander", re.IGNORECASE)


def commander_eligibility_line(line: str) -> bool:
    """Whether ``line`` is a RULE 903.3 "~ can be your commander." sentence —
    see `_COMMANDER_ELIGIBLE_RE`. Claimed at the `gate._process_line` level
    (before this module's `static_effect_specs` even runs), not through an
    `EffectSpec`, since it carries no behaviour to bind."""
    return bool(_COMMANDER_ELIGIBLE_RE.fullmatch(line.strip().rstrip(".").strip()))


#: The subject phrases an Aura/Equipment/Fortification's own buff clause is
#: printed with — a closed list (not a general noun-phrase parse like
#: `_scope`, since only these five shapes actually appear on cards) rather
#: than any combination of "equipped/enchanted/fortified" x
#: "creature/land/permanent" ("equipped land"/"fortified creature" don't
#: exist and stay unclaimed).
_ATTACHED_SUBJECTS = (
    "equipped creature",
    "enchanted creature",
    "fortified land",
    "enchanted permanent",
    "enchanted land",
)
_ATTACHED_SUBJECT_PATTERN = "|".join(re.escape(s) for s in _ATTACHED_SUBJECTS)

# "Enchanted/equipped <subject> doesn't untap during its controller's untap
# step."  (RULE 502.3-adjacent, attached-permanent form — e.g. Paralyzing
# Grasp) — the Aura/Equipment-grant sibling of `_NO_UNTAP_RE` above.
_NO_UNTAP_ATTACHED_RE = re.compile(
    rf"(?P<subject>{_ATTACHED_SUBJECT_PATTERN}) doesn'?t untap during its "
    r"controller'?s untap step",
    re.IGNORECASE,
)

# "~"/an attached-permanent subject can't attack, can't block, can't be
# blocked, or must attack each combat (RULE 508.1a/509.1a self-restrictions)
# — modeled as synthetic layer-6 "keyword" flags (`"cant_attack"`/
# `"cant_block"`/`"cant_be_blocked"`/`"attacks_if_able"`; *not* real RULE 702
# keywords, just internal markers `game/combat.py`'s `has()` and the engine's
# `_can_attack`/`can_block`/attack-declaration enforcement check alongside
# the real keyword union) reusing the exact same `grant_keyword` StaticAbility
# / layer-6 plumbing — zero new engine code for the restriction half. The
# "…and its activated abilities can't be activated" tail reuses the existing
# board-wide `activation_prohibition` family (RULE 602) scoped to just this
# one object instead of a card-type filter — the selector vocabulary
# (``affects="self"``/``"attached_permanent"``) already supports that.
# Deliberately excludes every qualified/conditional variant ("except by…",
# "unless…", "…alone", "…unless they're mana abilities") — `fullmatch` leaves
# the trailing clause unconsumed so those stay unclaimed (fail-closed) rather
# than guess at a different rule.
_COMBAT_RESTRICTION_SUBJECT_PATTERN = rf"~|{_ATTACHED_SUBJECT_PATTERN}"
_CANT_ATTACK_OR_BLOCK_LOCK_RE = re.compile(
    rf"(?P<subject>{_COMBAT_RESTRICTION_SUBJECT_PATTERN}) can'?t attack or "
    r"block, and its activated abilities can'?t be activated",
    re.IGNORECASE,
)
_CANT_ATTACK_OR_BLOCK_RE = re.compile(
    rf"(?P<subject>{_COMBAT_RESTRICTION_SUBJECT_PATTERN}) can'?t attack or block",
    re.IGNORECASE,
)
_CANT_BLOCK_AND_CANT_BE_BLOCKED_RE = re.compile(
    rf"(?P<subject>{_COMBAT_RESTRICTION_SUBJECT_PATTERN}) can'?t block and "
    r"can'?t be blocked",
    re.IGNORECASE,
)
_CANT_ATTACK_RE = re.compile(
    rf"(?P<subject>{_COMBAT_RESTRICTION_SUBJECT_PATTERN}) can'?t attack", re.IGNORECASE
)
_CANT_BLOCK_RE = re.compile(
    rf"(?P<subject>{_COMBAT_RESTRICTION_SUBJECT_PATTERN}) can'?t block", re.IGNORECASE
)
_CANT_BE_BLOCKED_RE = re.compile(
    rf"(?P<subject>{_COMBAT_RESTRICTION_SUBJECT_PATTERN}) can'?t be blocked",
    re.IGNORECASE,
)
_ATTACKS_IF_ABLE_RE = re.compile(
    rf"(?P<subject>{_COMBAT_RESTRICTION_SUBJECT_PATTERN}) attacks each combat if able",
    re.IGNORECASE,
)


def _combat_restriction_affects(subject: str) -> str:
    return "self" if subject == "~" else "attached_permanent"


def _combat_restriction_specs(
    subject: str, flags: list[str], lock: bool = False
) -> list[EffectSpec]:
    affects = _combat_restriction_affects(subject)
    specs = [EffectSpec("grant_keyword", {"keywords": flags, "affects": affects})]
    if lock:
        specs.append(EffectSpec("activation_prohibition", {"affects": affects}))
    return specs


# "As ~ enters, choose a creature type."/"As ~ enters, choose a color."
# (RULE 601.2b — a characteristic-defining choice made *as part of*
# entering, not a triggered ability) — recognised separately from every
# other family in this module: the segmenter wraps its `EffectSpec`s as an
# ``enter_replacement`` `AbilitySpec` (RULE 614.1c/614.12's family, the same
# one Clever Impersonator's hand-authored "enter as a copy" uses) rather than
# ``static``, so `enter_choice_specs` below is a sibling entry point to
# `static_effect_specs`, not folded into it — see `segmenter.segment_line`'s
# call site. The choice itself is offered interactively by `RulesEngine.
# _offer_enter_choices` and stamped onto `GameObject.chosen_type`/
# `chosen_color`, which the dynamic ``subtype_from_source``/
# ``color_from_source`` selector params below (and `_IS_CHOSEN_TYPE_RE`) read
# back.
_CHOOSE_CREATURE_TYPE_ON_ENTER_RE = re.compile(
    r"as ~ enters, choose a creature type", re.IGNORECASE
)
_CHOOSE_COLOR_ON_ENTER_RE = re.compile(r"as ~ enters, choose a color", re.IGNORECASE)


def enter_choice_specs(clause: str) -> Optional[list[EffectSpec]]:
    """`EffectSpec`s for a RULE 601.2b "as ~ enters, choose a …" ``clause``,
    or ``None`` — see the module comment above `_CHOOSE_CREATURE_TYPE_ON_
    ENTER_RE`. Called by `segmenter.segment_line` *before*
    `static_effect_specs`, since the two clause families are wrapped as
    different `AbilitySpec.ability_kind`s (``enter_replacement`` vs.
    ``static``).
    """
    text = clause.strip().rstrip(".").strip()
    if _CHOOSE_CREATURE_TYPE_ON_ENTER_RE.fullmatch(text):
        return [EffectSpec("choose_creature_type_on_enter", {})]
    if _CHOOSE_COLOR_ON_ENTER_RE.fullmatch(text):
        return [EffectSpec("choose_color_on_enter", {})]
    return None


# "~ is the chosen type in addition to its other types." (RULE 601.2b/613.4a,
# A-Thran Portal/Adaptive Automaton-shaped self grant) — the layer-4 sibling
# of the dynamic anthem/grant ``subtype_from_source`` params above, scoped to
# just the source itself (``affects="self"``) rather than a controlled group.
_IS_CHOSEN_TYPE_RE = re.compile(
    r"~ is the chosen type in addition to its other types", re.IGNORECASE
)

# "You control enchanted creature/permanent." (Mind Control/Control Magic-
# shaped, RULE 613.2 layer-2 control-grant) — the existing `control_change`
# `StaticAbility` already defaults to ``affects="attached_permanent"`` and a
# controller of "the source's own controller" (exactly "you"), so this needed
# no new engine code, only the parser recognition.
_CONTROL_GRANT_RE = re.compile(
    r"you control (?:enchanted creature|enchanted permanent)", re.IGNORECASE
)

# "<equipped/enchanted/fortified subject> [gets +N/+N and] has \"<ability>\""
# (Sword-of-X-and-Y/Assassin Gauntlet/Caustic Tar-shaped, Umbral Mantle/
# Squirrel Nest-shaped) — an Aura/Equipment granting its host a *full*
# ability rather than a flag keyword. The quoted text is itself an ordinary
# ability line, so it's parsed the same way any top-level card's own line
# would be (`segmenter.segment_line`, imported lazily in
# `_quoted_ability_grant_effects` below — `segmenter` imports *this* module,
# so a module-level import would cycle) and wrapped as a
# `grant_triggered_ability`/`grant_activated_ability` when that recursive
# parse comes back a plain, unconditional shape: a self-scoped trigger on
# one of `_GRANTABLE_TRIGGER_EVENTS`, or a bare `<cost>: <effect>` activated
# ability (fail-closed on everything else: a controller-scoped phase
# trigger like "at the beginning of your upkeep" granted this way is a
# pre-existing gap, not special to grants; see `_GRANTABLE_TRIGGER_EVENTS`).
_ATTACHED_QUOTED_ANTHEM_GRANT_RE = re.compile(
    rf'(?P<subject>{_ATTACHED_SUBJECT_PATTERN}) gets (?P<p>[+-]\d+)/(?P<t>[+-]\d+) '
    r'and has "(?P<inner>.+)"',
    re.IGNORECASE | re.DOTALL,
)
_ATTACHED_QUOTED_GRANT_RE = re.compile(
    rf'(?P<subject>{_ATTACHED_SUBJECT_PATTERN}) has "(?P<inner>.+)"',
    re.IGNORECASE | re.DOTALL,
)


def _quoted_ability_grant_effects(inner: str) -> Optional[EffectSpec]:
    """Recursively parse a quoted granted-ability body into a
    `grant_triggered_ability`/`grant_activated_ability` `EffectSpec`, or
    ``None`` if it isn't a plain self-scoped trigger on a
    `_GRANTABLE_TRIGGER_EVENTS` event, or a plain `<cost>: <effect>`
    activated ability (see the module comment above
    `_ATTACHED_QUOTED_GRANT_RE`)."""
    from ..segmenter import segment_line  # lazy: segmenter imports this module

    segment = segment_line(
        inner.strip(),
        allow_spell_effect=False,
        provenance=ParserProvenance(version="nested", source="rule:oracle"),
    )
    spec = segment.spec
    if spec is None or spec.modes:
        return None

    if spec.ability_kind == "activated":
        # "<host> has '{cost}: <effect>.'" (Umbral Mantle/Squirrel
        # Nest-shaped) — layer 6, ability-adding (RULE 613.7f), granting a
        # full activated ability. `once_per_turn`/`sorcery_speed_only`
        # markers mirror `effect_binder.bind_ability`'s own stripping for a
        # top-level activated ability (no real card needs either yet, but a
        # quoted "Activate only once each turn." shouldn't silently leak a
        # marker EffectSpec into `grant_effects` for `build_effects` to choke
        # on) — this nested parse doesn't go through `bind_ability` itself.
        effect_specs = spec.effects
        once_per_turn = any(e.type == ONCE_PER_TURN_MARKER for e in effect_specs)
        sorcery_speed_only = any(e.type == SORCERY_SPEED_MARKER for e in effect_specs)
        effect_specs = [
            e for e in effect_specs
            if e.type not in (ONCE_PER_TURN_MARKER, SORCERY_SPEED_MARKER)
        ]
        return EffectSpec("grant_activated_ability", {
            "cost": dict(spec.cost or {}),
            "grant_effects": [{"type": e.type, "params": e.params} for e in effect_specs],
            "once_per_turn": once_per_turn,
            "sorcery_speed_only": sorcery_speed_only,
            "affects": "attached_permanent",
        })

    if spec.ability_kind != "triggered":
        return None
    trigger = spec.trigger or {}
    if trigger.get("event") not in _GRANTABLE_TRIGGER_EVENTS:
        return None
    if trigger.get("condition") != {"subject": "self"}:
        return None  # a "group"/other subject wouldn't mean the same thing once regranted
    params: dict = {
        "trigger_event": trigger["event"],
        "grant_effects": [{"type": e.type, "params": e.params} for e in spec.effects],
        "optional": spec.optional,
        "affects": "attached_permanent",
    }
    if trigger.get("filter"):  # RULE 120.3 DAMAGE combat/is_player filter
        params["filter"] = dict(trigger["filter"])
    return EffectSpec("grant_triggered_ability", params)


# "<equipped/enchanted/fortified subject> gets +N/+N [and has <keywords>]"
# (attached-permanent anthem, +grant) — singular "gets"/"has", unlike the
# plural "get"/"have" of `_ANTHEM_RE`/`_GRANT_RE` above (those two families
# never collide on the same clause text).
_ATTACHED_ANTHEM_RE = re.compile(
    rf"(?P<subject>{_ATTACHED_SUBJECT_PATTERN}) "
    r"gets (?P<p>[+-]\d+)/(?P<t>[+-]\d+)"
    r"(?: and has (?P<kw>[a-z][a-z, ]*))?",
    re.IGNORECASE,
)
# "<equipped/enchanted/fortified subject> has <keywords>"  (keyword-only grant)
_ATTACHED_GRANT_RE = re.compile(
    rf"(?P<subject>{_ATTACHED_SUBJECT_PATTERN}) has (?P<kw>[a-z][a-z, ]*)",
    re.IGNORECASE,
)


class _Scope(NamedTuple):
    subtype: Optional[str]  # a creature type ("Goblin"), or None for "creatures"
    tokens: bool  # True for "<…> tokens" (Intangible Virtue)
    colors: list  # WUBRG/C symbols; empty = no colour restriction (Bad Moon)


def _singularize(word: str) -> str:
    """A plural creature type → singular ("goblins"→"goblin", "elves"→"elf")."""
    if word.endswith("ves"):
        return word[:-3] + "f"
    if word.endswith("s"):
        return word[:-1]
    return word


def _scope(body: str) -> Optional[_Scope]:
    """Parse a scope phrase into a `_Scope`, or ``None`` for a non-creature scope.

    Handles a leading global marker ("all"/"each"), leading colour words
    ("black", "white and blue"), "creatures", a plural type ("goblins"),
    "<type> creatures", and the "<…> tokens" variants — always fail-closed
    (returns ``None`` rather than guess a scope it doesn't recognise).
    """
    words = body.split()
    while words and words[0] in ("all", "each"):  # global emphasis, no scope change
        words = words[1:]

    colors: list = []
    while words:
        if words[0] in _COLOR_WORDS:
            colors.append(_COLOR_WORDS[words[0]])
            words = words[1:]
        elif words[0] in ("and", "or") and len(words) > 1 and words[1] in _COLOR_WORDS:
            words = words[1:]  # skip a colour connector ("white and blue")
        else:
            break

    tokens = False
    if words and words[-1] == "tokens":
        tokens = True
        words = words[:-1]
        if not words:  # bare "tokens" (creature tokens implied)
            return _Scope(None, True, colors)

    if words in (["creature"], ["creatures"]):
        return _Scope(None, tokens, colors)
    if not words:
        return None
    if words[-1] == "creatures":
        sub = _singularize(" ".join(words[:-1]))
    elif len(words) == 1:
        sub = _singularize(words[0])
    else:
        return None  # multi-word non-"creatures" scope — don't guess
    if not sub or sub in _NONCREATURE_TYPES:
        return None
    return _Scope(sub.capitalize(), tokens, colors)


def _scope_params(scope: _Scope, m: "re.Match[str]") -> dict:
    """Build the `affects` + filter params from a scope and the clause match.

    ``affects`` is the base set; "you control" scopes it to the controller (and
    "other" excludes the source), while its absence makes the anthem global
    (RULE 613 — all creatures). Subtype/colour/tokens narrow the set further.
    """
    other = bool(m.group("scope"))
    yours = bool(m.group("yours"))
    if yours:
        params: dict = {"affects": "other_creatures_you_control" if other
                        else "creatures_you_control"}
    else:
        params = {"affects": "all_creatures"}
        if other:  # a global "Other creatures …" excludes just the source
            params["exclude_self"] = True
    if scope.subtype:
        params["subtype"] = scope.subtype
    # "… of the chosen type/color …" (RULE 601.2b) — a dynamic sibling of the
    # literal subtype/colour params above, read fresh off the ability's own
    # source at recompute time (`continuous.group_selector_objects`). Only
    # `_ANTHEM_RE`/`_GRANT_RE` carry a "chosen" group; every other caller of
    # this function matches a body with no such group at all.
    chosen = m.groupdict().get("chosen")
    if chosen == "type":
        params["subtype_from_source"] = True
    elif chosen == "color":
        params["color_from_source"] = True
    if scope.tokens:
        params["tokens"] = True
    if scope.colors:
        params["color"] = scope.colors
    return params


def _flag_keywords(text: str) -> Optional[list[str]]:
    """A "have <keywords>" list → grantable keyword slugs, or ``None`` if any
    isn't recognised (fail-closed — most other granted parametric keywords,
    e.g. "ward {2}", need behaviour the grant can't express yet).

    Almost every entry must be a parameterless FLAG keyword ("flying",
    "trample"). The one parametric exception: a landwalk variant
    ("forestwalk", "islandwalk", …) — RULE 702.14's land type lives in the
    slug itself, and `combat._landwalk_slugs` already matches any
    ``granted_keywords`` entry ending in "walk" directly, so the grant
    mechanism needs no separate quality param the way "protection from
    <color>" would. A bare "landwalk" with no type (never printed on a real
    card) still fails closed.
    """
    slugs: list[str] = []
    for part in re.split(r",|\band\b", text):
        part = part.strip()
        if not part:
            continue
        slug = keyword_slug(part)
        kdef = KEYWORDS.get(slug)
        if kdef is not None and kdef.shape is KeywordShape.FLAG:
            slugs.append(kdef.slug)
            continue
        resolved = resolve_keyword(slug)
        if resolved is not None and resolved.slug == "landwalk" and slug != "landwalk":
            slugs.append(slug)
            continue
        return None
    return slugs or None


def static_effect_specs(clause: str) -> Optional[list[EffectSpec]]:
    """`EffectSpec`s for a static anthem/keyword-grant ``clause``, or ``None``.

    Full-matches the clause (like the one-shot handler table) so a partial or
    "until end of turn" phrasing isn't claimed. A compound "get +N/+N and have
    <keywords>" emits both an ``anthem`` and a ``grant_keyword`` spec. The specs
    carry ``affects`` + optional ``subtype``/``tokens`` for the layer engine.
    Also claims the attached-permanent shape ("equipped/enchanted creature
    gets +N/+N [and has <keywords>]", "equipped/enchanted creature has
    <keywords>") with ``affects="attached_permanent"`` — see
    `_ATTACHED_SUBJECTS` above.
    """
    text = clause.strip().rstrip(".").strip()

    # "This spell can't be countered." (RULE 118-area) — printed on a
    # permanent as a standing line even though it only matters while the
    # object is still a spell on the stack; `catalogue.handlers` claims the
    # identical phrase for the instant/sorcery spell_effect path, see
    # `CANT_BE_COUNTERED_RE`'s docstring for why both need it.
    if CANT_BE_COUNTERED_RE.fullmatch(text):
        return [EffectSpec("cant_be_countered", {})]

    m = _ACTIVATION_PROHIBITION_RE.fullmatch(text)
    if m is not None:
        card_type = _singularize(m.group("word"))
        if card_type not in _CARD_TYPE_WORDS:
            return None  # fail-closed — an unrecognised type-scope
        return [EffectSpec("activation_prohibition", {"card_type": card_type})]

    m = _SPELL_COST_TAX_RE.fullmatch(text)
    if m is not None:
        word = (m.group("word") or "").lower()
        # A bare "spells cost {N} more/less to cast" (no type word — Sphere of
        # Resistance) taxes *every* spell: a falsy ``spell_type`` means "no
        # type filter" in `continuous.cost_reduction_for`. A typed variant
        # must name a recognised card type (fail-closed).
        if word and word not in _SPELL_TYPE_WORDS:
            return None
        params: dict = {
            "affects": "all_spells",
            "generic": int(m.group("n")),
            "increase": m.group("dir") == "more",
        }
        if word:
            params["spell_type"] = word
        return [EffectSpec("cost_reduction", params)]

    m = _CAST_LIMIT_RE.fullmatch(text)
    if m is not None:
        return [EffectSpec("cast_limit", {"max_per_turn": int(m.group("n"))})]

    m = _EXTRA_LAND_DROP_RE.fullmatch(text)
    if m is not None:
        affects = "each_player" if m.group("subject").lower() == "each player" else "you"
        return [EffectSpec("extra_land_drop", {"affects": affects, "count": count_of(m.group("n"))})]

    m = _NO_MAX_HAND_SIZE_RE.fullmatch(text)
    if m is not None:
        affects = "each_player" if m.group("subject").lower() == "players have" else "you"
        return [EffectSpec("no_max_hand_size", {"affects": affects})]

    if _RADIATION_LIFE_GAIN_RE.fullmatch(text):
        return [EffectSpec("radiation_life_gain", {})]

    if _NO_UNTAP_OPTIONAL_RE.fullmatch(text):
        return [EffectSpec("no_untap_optional", {})]

    if _NO_UNTAP_RE.fullmatch(text):
        return [EffectSpec("no_untap", {"affects": "self"})]

    m = _NO_UNTAP_ATTACHED_RE.fullmatch(text)
    if m is not None:
        return [EffectSpec("no_untap", {"affects": "attached_permanent"})]

    m = _TRIGGER_PROHIBITION_RE.fullmatch(text)
    if m is not None:
        subject_type = _singularize(m.group("word"))
        if subject_type not in _CARD_TYPE_WORDS:
            return None
        return [
            EffectSpec(
                "trigger_prohibition",
                {"event": "ENTERS_BATTLEFIELD", "subject_type": subject_type},
            )
        ]

    m = _OPPONENTS_ENTER_TAPPED_RE.fullmatch(text)
    if m is not None:
        card_types = [_singularize(w) for w in m.group("words").split(" and ")]
        if any(t not in _CARD_TYPE_WORDS for t in card_types):
            return None
        specs = []
        for card_type in card_types:
            params: dict = {"affects": "opponents_permanents", "card_type": card_type}
            if m.group("nonbasic"):
                params["nonbasic"] = True
            specs.append(EffectSpec("enters_tapped_static", params))
        return specs

    m = _ALL_ENTER_TAPPED_RE.fullmatch(text)
    if m is not None:
        card_types = [_singularize(w) for w in m.group("words").split(" and ")]
        if any(t not in _CARD_TYPE_WORDS for t in card_types):
            return None
        specs = []
        for card_type in card_types:
            params = {"affects": "all_permanents", "card_type": card_type}
            if m.group("nonbasic"):
                params["nonbasic"] = True
            specs.append(EffectSpec("enters_tapped_static", params))
        return specs

    m = _TYPE_OVERWRITE_RE.fullmatch(text)
    if m is not None:
        basic_type = _BASIC_LAND_WORDS.get(m.group("word").lower())
        if basic_type is None:
            return None  # fail-closed — an unrecognised "are <X>" overwrite
        color = _BASIC_LAND_COLOR[basic_type.lower()]
        shared = {"affects": "all_lands", "nonbasic": True}
        return [
            EffectSpec("type_change", {**shared, "set_subtypes": [basic_type]}),
            EffectSpec("grant_mana_ability", {**shared, "mana": [{color: 1}]}),
        ]

    # Attached-permanent shape first ("equipped creature gets +2/+2 [and has
    # <keywords>]") — a closed subject list, so this never competes with the
    # "you control" scopes below (singular "gets"/"has" vs. their plural
    # "get"/"have"). `affects="attached_permanent"` is honoured by both
    # `anthem` (layer 7c) and `grant_keyword` (layer 6) in `game/continuous.py`.
    m = _ATTACHED_ANTHEM_RE.fullmatch(text)
    if m is not None:
        specs = [
            EffectSpec("anthem", {"power": int(m.group("p")), "toughness": int(m.group("t")),
                                   "affects": "attached_permanent"})
        ]
        if m.group("kw"):  # "… and has <keywords>" tail
            keywords = _flag_keywords(m.group("kw"))
            if keywords is None:
                return None  # e.g. a granted landwalk — fail-closed, whole clause
            specs.append(EffectSpec("grant_keyword", {"keywords": keywords,
                                                        "affects": "attached_permanent"}))
        return specs

    # Attached-permanent keyword-only grant ("equipped creature has trample").
    m = _ATTACHED_GRANT_RE.fullmatch(text)
    if m is not None:
        keywords = _flag_keywords(m.group("kw"))
        if keywords is None:
            return None
        return [EffectSpec("grant_keyword", {"keywords": keywords, "affects": "attached_permanent"})]

    # Combat-restriction family ("~ can't attack.", "enchanted creature can't
    # be blocked.", "~ attacks each combat if able.", …) — see
    # `_combat_restriction_specs` above. Ordered most-specific-first so a
    # combined clause matches its own row rather than a shorter prefix; since
    # every branch uses `fullmatch`, a shorter regex simply fails on any
    # unconsumed trailing text (fail-closed), so the ordering is for clarity
    # rather than correctness.
    m = _CANT_ATTACK_OR_BLOCK_LOCK_RE.fullmatch(text)
    if m is not None:
        return _combat_restriction_specs(m.group("subject"), ["cant_attack", "cant_block"], lock=True)

    m = _CANT_ATTACK_OR_BLOCK_RE.fullmatch(text)
    if m is not None:
        return _combat_restriction_specs(m.group("subject"), ["cant_attack", "cant_block"])

    m = _CANT_BLOCK_AND_CANT_BE_BLOCKED_RE.fullmatch(text)
    if m is not None:
        return _combat_restriction_specs(m.group("subject"), ["cant_block", "cant_be_blocked"])

    m = _CANT_ATTACK_RE.fullmatch(text)
    if m is not None:
        return _combat_restriction_specs(m.group("subject"), ["cant_attack"])

    m = _CANT_BLOCK_RE.fullmatch(text)
    if m is not None:
        return _combat_restriction_specs(m.group("subject"), ["cant_block"])

    m = _CANT_BE_BLOCKED_RE.fullmatch(text)
    if m is not None:
        return _combat_restriction_specs(m.group("subject"), ["cant_be_blocked"])

    m = _ATTACKS_IF_ABLE_RE.fullmatch(text)
    if m is not None:
        return _combat_restriction_specs(m.group("subject"), ["attacks_if_able"])

    if _CONTROL_GRANT_RE.fullmatch(text):
        return [EffectSpec("control_change", {})]

    if _IS_CHOSEN_TYPE_RE.fullmatch(text):
        return [EffectSpec("type_change", {"affects": "self", "add_subtypes_from_source": True})]

    m = _ATTACHED_QUOTED_ANTHEM_GRANT_RE.fullmatch(text)
    if m is not None:
        grant = _quoted_ability_grant_effects(m.group("inner"))
        if grant is None:
            return None
        return [
            EffectSpec("anthem", {"power": int(m.group("p")), "toughness": int(m.group("t")),
                                   "affects": "attached_permanent"}),
            grant,
        ]

    m = _ATTACHED_QUOTED_GRANT_RE.fullmatch(text)
    if m is not None:
        grant = _quoted_ability_grant_effects(m.group("inner"))
        if grant is None:
            return None
        return [grant]

    m = _ANTHEM_RE.fullmatch(text)
    if m is not None:
        scope = _scope(m.group("body"))
        if scope is None:
            return None
        params = _scope_params(scope, m)
        specs = [
            EffectSpec("anthem",
                       {"power": int(m.group("p")), "toughness": int(m.group("t")), **params})
        ]
        if m.group("kw"):  # "… and have <keywords>" tail
            keywords = _flag_keywords(m.group("kw"))
            if keywords is None:
                return None  # e.g. a granted landwalk — fail-closed, whole clause
            specs.append(EffectSpec("grant_keyword", {"keywords": keywords, **params}))
        return specs

    m = _QUOTED_GRANT_RE.fullmatch(text)
    if m is not None:
        scope = _scope(m.group("body"))
        if scope is None:
            return None
        grant = _quoted_ability_grant_effects(m.group("inner"))
        if grant is None:
            return None
        grant.params.update(_scope_params(scope, m))
        return [grant]

    m = _GRANT_RE.fullmatch(text)
    if m is not None:
        scope = _scope(m.group("body"))
        if scope is None:
            return None
        keywords = _flag_keywords(m.group("kw"))
        if keywords is None:
            return None
        return [EffectSpec("grant_keyword", {"keywords": keywords, **_scope_params(scope, m)})]

    return None
