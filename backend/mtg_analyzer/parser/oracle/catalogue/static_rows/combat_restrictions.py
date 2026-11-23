"""Static-ability helpers: combat restrictions (split from `static_handlers` by PAR-172's method, ENG-59)."""

from __future__ import annotations

import re
from typing import Any, Optional
from ...spec import EffectSpec
from ..subgrammars import COLOR_LETTERS
from .object_scope import parse_scope, parse_scope_params, permanent_scope_params, permanent_type_scope

#: The subject phrases an Aura/Equipment/Fortification's own buff clause is
#: printed with — a closed list (not a general noun-phrase parse like
#: `parse_scope`, since only these five shapes actually appear on cards) rather
#: than any combination of "equipped/enchanted/fortified" x
#: "creature/land/permanent" ("equipped land"/"fortified creature" don't
#: exist and stay unclaimed).
_ATTACHED_SUBJECTS = (
    "equipped creature",
    "enchanted creature",
    "fortified land",
    "enchanted permanent",
    "enchanted land",
    # PAR-142: the Animate-Artifact family (Ensoul Artifact, Mightstone's Animation, Zoetic Glyph).
    "enchanted artifact",
    "enchanted planeswalker",
)
ATTACHED_SUBJECT_PATTERN = "|".join(re.escape(s) for s in _ATTACHED_SUBJECTS)

# RULE 613.4b / RULE 105.2: a standing colour statement — "~ is all colors." (Sphinx of the Guildpact),
# "All creatures are black." (Darkest Hour), "All Slivers are colorless." (Ghostflame Sliver), "Enchanted creature
# gets +3/+1 and is black." (Sinister Strength). One layer-5 `color_change` over whichever scope (self / attached /
# group) the subject names, with the printed colour set REPLACING the object's colours. "colorless" is the empty set.
_COLOR_SET = r"colorless|all colors|(?:white|blue|black|red|green)(?: and (?:white|blue|black|red|green))*"
_COLOR_STATEMENT_RE = re.compile(
    rf"(?P<subject>~|(?P<attached>{ATTACHED_SUBJECT_PATTERN})|(?P<quantified>all |each )?(?P<scope>other )?"
    rf"(?P<body>[a-z][a-z ]*?)(?P<yours> you control)?) (?:is|are) (?P<colors>{_COLOR_SET})",
    re.IGNORECASE,
)
_ATTACHED_PUMP_COLOR_RE = re.compile(
    rf"(?P<attached>{ATTACHED_SUBJECT_PATTERN}) gets (?P<p>[+-]\d+)/(?P<t>[+-]\d+) and is (?P<colors>{_COLOR_SET})",
    re.IGNORECASE,
)
_ALL_COLORS = ["W", "U", "B", "R", "G"]


def _color_statement_letters(phrase: str) -> list[str]:
    """The WUBRG letters a `_COLOR_SET` phrase names: "colorless" is the empty set, "all colors" every colour."""
    phrase = phrase.lower()
    if phrase == "colorless":
        return []
    if phrase == "all colors":
        return list(_ALL_COLORS)
    return [COLOR_LETTERS[word] for word in phrase.split(" and ")]


def color_statement_specs(text: str) -> Optional[list[EffectSpec]]:
    pump = _ATTACHED_PUMP_COLOR_RE.fullmatch(text)
    if pump is not None:
        return [
            EffectSpec("anthem", {"power": int(pump.group("p")), "toughness": int(pump.group("t")),
                                  "affects": "attached_permanent"}),
            EffectSpec("color_change", {"colors": _color_statement_letters(pump.group("colors")),
                                        "affects": "attached_permanent"}),
        ]
    m = _COLOR_STATEMENT_RE.fullmatch(text)
    if m is None:
        return None
    if m.group("subject") == "~":
        params: Optional[dict] = {"affects": "self"}
    elif m.group("attached"):
        params = {"affects": "attached_permanent"}
    else:
        if not (m.group("quantified") or m.group("yours")):
            return None  # a bare noun ("it", "that creature") is a referent, not a standing group
        body = m.group("body").strip()
        scope = parse_scope(body)
        if scope is not None and not scope.colors:
            params = parse_scope_params(scope, m)
        else:
            word = permanent_type_scope(body)
            params = None if word is None else permanent_scope_params(word, m)
    if params is None:
        return None
    return [EffectSpec("color_change", {"colors": _color_statement_letters(m.group("colors")), **params})]

# "Enchanted/equipped <subject> doesn't untap during its controller's untap
# step."  (RULE 502.3-adjacent, attached-permanent form — e.g. Paralyzing
# Grasp) — the Aura/Equipment-grant sibling of `NO_UNTAP_RE` above.
NO_UNTAP_ATTACHED_RE = re.compile(
    rf"(?P<subject>{ATTACHED_SUBJECT_PATTERN}) doesn'?t untap during its "
    r"controller'?s untap step",
    re.IGNORECASE,
)

# RULE 613.1f / 613.4c: standing ability removal on an Aura's host,
# composed with the same host's P/T modifier or untap restriction. These are
# attached statics (RULE 611.3b), not a one-shot removal lasting past the Aura.
ATTACHED_ABILITY_LOSS_RE = re.compile(
    r"(?P<subject>enchanted creature|enchanted permanent) "
    r"(?:(?P<pump>gets [+-]\d+/[+-]\d+) and )?loses all abilities"
    r"(?: and (?P<no_untap>doesn'?t untap during its controller'?s untap step))?",
    re.IGNORECASE,
)

# "~"/an attached-permanent subject can't attack, can't block, can't be
# blocked, or must attack each combat (RULE 508.1a/509.1a self-restrictions)
# — modeled as synthetic layer-6 "keyword" flags (`"cant_attack"`/
# `"cant_block"`/`"cant_be_blocked"`/`"attacks_if_able"`/`"must_be_blocked"`/
# `"all_must_block"`; *not* real RULE 702 keywords, just internal markers
# `game/combat.py`'s `has()` and the engine's `_can_attack`/`can_block`/
# attack-declaration/block-requirement enforcement checks alongside
# the real keyword union) reusing the exact same `grant_keyword` StaticAbility
# / layer-6 plumbing — zero new engine code for the restriction half. The
# "…and its activated abilities can't be activated" tail reuses the existing
# board-wide `activation_prohibition` family (RULE 602) scoped to just this
# one object instead of a card-type filter — the selector vocabulary
# (``affects="self"``/``"attached_permanent"``) already supports that.
# The *qualified* variants ("except by…", "unless…", "…alone") are claimed
# separately, by the `combat_restriction` family further down — each regex
# here is `fullmatch`ed, so a trailing qualifier leaves this row unmatched
# and falls through to those rather than being silently dropped. RULE
# 509.1b's multi-block *permissions* ("~ can block an additional creature
# each combat."/"~ can block any number of creatures.") ride that
# `combat_restriction` family directly instead (`"extra_blocks"`/
# `"unlimited_blocks"`), since the count actually matters there.
_COMBAT_RESTRICTION_SUBJECT_PATTERN = rf"~|{ATTACHED_SUBJECT_PATTERN}"
CANT_ATTACK_OR_BLOCK_LOCK_RE = re.compile(
    rf"(?P<subject>{_COMBAT_RESTRICTION_SUBJECT_PATTERN}) can'?t attack"
    r"(?: or block|(?P<crew>, block, or crew vehicles))(?:, and |\. )its activated abilities can'?t be activated"
    r"(?P<mana_exception> unless they'?re mana abilities)?",
    re.IGNORECASE,
)
CANT_ATTACK_OR_BLOCK_RE = re.compile(
    rf"(?P<subject>{_COMBAT_RESTRICTION_SUBJECT_PATTERN}) can'?t attack(?: or block|(?P<crew>, block, or crew vehicles))",
    re.IGNORECASE,
)
CANT_BLOCK_AND_CANT_BE_BLOCKED_RE = re.compile(
    rf"(?P<subject>{_COMBAT_RESTRICTION_SUBJECT_PATTERN}) can'?t block and "
    r"can'?t be blocked",
    re.IGNORECASE,
)
CANT_ATTACK_RE = re.compile(
    rf"(?P<subject>{_COMBAT_RESTRICTION_SUBJECT_PATTERN}) can'?t attack", re.IGNORECASE
)
#: RULE 508.1g attack tax — "Creatures can't attack you unless their
#: controller pays {N} for each creature they control that's attacking you."
#: (Propaganda / Ghostly Prison / Windborn Muse). A `"you"`-scoped marker
#: static (`EffectRegistry` ``"attack_tax"`` → `continuous.attack_tax_per_
#: creature_for`, enforced in `combat_mixin.declare_attackers`), NOT a
#: `combat_restriction` flag on the attackers. Anchored to exactly this
#: printed sentence plus the two count-defined siblings. Sphere of Safety
#: explicitly extends its protection to planeswalkers its controller owns;
#: the marker carries that scope because RULE 508.1g's cost check sees the
#: chosen defender, not merely that defender's player. Other qualified
#: variants ("except by <text>") stay unclaimed (fail-closed).
ATTACK_TAX_RE = re.compile(
    r"creatures can'?t attack you(?P<planeswalkers> or planeswalkers you control)? "
    r"unless their controller pays (?:\{(?P<n>\d+)\}|\{x\}) "
    r"for each (?:creature they control that'?s attacking you|of those creatures)"
    r"(?:, where x is the number of (?P<x_source>enchantments you control|basic land types among lands you control))?",
    re.IGNORECASE,
)
CANT_BLOCK_RE = re.compile(
    rf"(?P<subject>{_COMBAT_RESTRICTION_SUBJECT_PATTERN}) can'?t block", re.IGNORECASE
)
CANT_BE_BLOCKED_RE = re.compile(
    rf"(?P<subject>{_COMBAT_RESTRICTION_SUBJECT_PATTERN}) can'?t be blocked",
    re.IGNORECASE,
)
ATTACKS_IF_ABLE_RE = re.compile(
    rf"(?P<subject>{_COMBAT_RESTRICTION_SUBJECT_PATTERN}) attacks each combat if able",
    re.IGNORECASE,
)

# RULE 509.1c/d combat *requirements* — the mirror image of the restriction
# family above (they force a block rather than forbid one), but the same two
# self/attached subjects and the same synthetic flag-keyword plumbing:
# "must_be_blocked"/"all_must_block" are consulted by `GameEngine.
# _enforce_block_requirements` exactly like `attacks_if_able` is by
# `_enforce_attacks_if_able`, both checked as the relevant declare step
# closes rather than at recompute time (a requirement needs to see who
# actually got blocked/declared, same reason the restrictions above do).
MUST_BE_BLOCKED_RE = re.compile(
    rf"(?P<subject>{_COMBAT_RESTRICTION_SUBJECT_PATTERN}) must be blocked if able",
    re.IGNORECASE,
)
#: RULE 509.1c: "~ must be blocked by exactly one creature if able" (Nacatl War-Pride) — the count-limited sibling.
MUST_BE_BLOCKED_BY_ONE_RE = re.compile(
    rf"(?P<subject>{_COMBAT_RESTRICTION_SUBJECT_PATTERN}) must be blocked by exactly (?:1|one) creature if able",
    re.IGNORECASE,
)
#: "All creatures able to block ~ do so." (Lure-shaped) — unlike every other
#: row in this family, the printed *subject* of the sentence is the set of
#: candidate blockers, not the restricted/required permanent itself (which
#: appears only as the object of "block …"), so it needs its own regex
#: rather than a `_QUALIFIED_SUBJECT`-shaped one.
ALL_MUST_BLOCK_RE = re.compile(
    rf"all creatures able to block (?P<subject>~|it|{ATTACHED_SUBJECT_PATTERN}) do so",
    re.IGNORECASE,
)

# RULE 509.1b multi-block *permissions* — same self/attached subject family,
# but a `combat_restriction` param entry (`extra_blocks`/`unlimited_blocks`)
# rather than a bare flag, since the count matters (`game/combat.py`'s
# `max_blocks_for`).
BLOCK_ADDITIONAL_RE = re.compile(
    rf"(?P<subject>{_COMBAT_RESTRICTION_SUBJECT_PATTERN}) can block an additional creature "
    r"each combat",
    re.IGNORECASE,
)
BLOCK_ANY_NUMBER_RE = re.compile(
    rf"(?P<subject>{_COMBAT_RESTRICTION_SUBJECT_PATTERN}) can block any number of creatures",
    re.IGNORECASE,
)
#: "…can block an additional **N** creatures each combat" — the counted form
#: of `BLOCK_ADDITIONAL_RE` (Temperamental Oozewagg's "an additional 99").
BLOCK_ADDITIONAL_N_RE = re.compile(
    rf"(?P<subject>{_COMBAT_RESTRICTION_SUBJECT_PATTERN}) can block an additional "
    r"(?P<n>\d+) creatures each combat",
    re.IGNORECASE,
)
#: RULE 508.1a attack *permission* — "~ can attack as though it didn't have
#: defender". Not a keyword removal (the creature keeps Defender); see
#: `combat.COMBAT_RESTRICTIONS`' ``attacks_as_though_no_defender``.
ATTACK_AS_THOUGH_NO_DEFENDER_RE = re.compile(
    rf"(?P<subject>{_COMBAT_RESTRICTION_SUBJECT_PATTERN}) can attack as though "
    r"(?:it|they) didn'?t have defender",
    re.IGNORECASE,
)

#: The combat *permission* tails that may follow a keyword grant in one
#: clause ("…has trample **and can attack as though it didn't have
#: defender**"). Each maps the tail text to its `combat_restriction` params;
#: the subject is the grant's own, so these carry no subject of their own.
_PERMISSION_TAIL_RES: list[tuple[re.Pattern[str], Any]] = [
    (re.compile(r"can attack as though (?:it|they) didn'?t have defender", re.I),
     lambda m: {"kind": "attacks_as_though_no_defender"}),
    (re.compile(r"can block an additional (?P<n>\d+) creatures each combat", re.I),
     lambda m: {"kind": "extra_blocks", "count": int(m.group("n"))}),
    (re.compile(r"can block an additional creature each combat", re.I),
     lambda m: {"kind": "extra_blocks", "count": 1}),
    (re.compile(r"can block any number of creatures", re.I),
     lambda m: {"kind": "unlimited_blocks"}),
]


def permission_tail_params(text: str) -> Optional[dict]:
    """A trailing combat-permission phrase → `combat_restriction` params.

    ``None`` for anything else, which fails the whole clause closed — the
    tail exists precisely because dropping it would leave a card that says
    "has trample and can attack as though it didn't have defender" granting
    only the trample, i.e. quietly wrong rather than merely unmodeled.
    """
    stripped = text.strip().rstrip(".").strip()
    for pattern, build in _PERMISSION_TAIL_RES:
        m = pattern.fullmatch(stripped)
        if m is not None:
            return build(m)
    return None


def combat_restriction_affects(subject: str) -> str:
    return "self" if subject == "~" else "attached_permanent"


def combat_restriction_specs(
    subject: str, flags: list[str], lock: bool = False, mana_exception: bool = False
) -> list[EffectSpec]:
    affects = combat_restriction_affects(subject)
    specs = [EffectSpec("grant_keyword", {"keywords": flags, "affects": affects})]
    if lock:
        params: dict = {"affects": affects}
        if mana_exception:
            # RULE 605.1a: "…unless they're mana abilities" (Imprisoned in
            # the Moon/Kasmina's Transmutation) — the same prohibition with a
            # carve-out `continuous.activation_prohibited` honours.
            params["except_mana_abilities"] = True
        specs.append(EffectSpec("activation_prohibition", params))
    return specs


# -- The *qualified* combat restrictions (RULE 508.1a / 509.1b) --------------
#
# Everything above is a plain flag ("~ can't attack."). Their qualified
# siblings carry a parameter — a blocker filter, a count, or an "unless"
# condition — and so bind to a ``combat_restriction`` `EffectSpec` instead,
# stamped onto `GameObject.combat_restrictions` and evaluated at combat time
# (`game/combat.py`'s `COMBAT_RESTRICTIONS` whitelist / `GameEngine.
# _combat_condition_met`). Still fail-closed: an unrecognised filter or
# condition returns ``None`` for the whole clause rather than dropping the
# qualifier and claiming the plain restriction, which would be strictly
# *wrong* behaviour rather than merely missing behaviour.
