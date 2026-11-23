"""Static-ability helpers: rows combat (split from `static_handlers` by PAR-172's method, ENG-59)."""

from __future__ import annotations

import re
from typing import Optional
from ...spec import EffectSpec
from ..combat_phrase import combat_tail
from ..quantifier_scope import object_set
from ..clause_reading import ClauseReading
from ..clause_hooks import static_effect_specs
from .combat_restrictions import (
    ALL_MUST_BLOCK_RE,
    ATTACHED_SUBJECT_PATTERN,
    ATTACKS_IF_ABLE_RE,
    ATTACK_AS_THOUGH_NO_DEFENDER_RE,
    ATTACK_TAX_RE,
    BLOCK_ADDITIONAL_N_RE,
    BLOCK_ADDITIONAL_RE,
    BLOCK_ANY_NUMBER_RE,
    CANT_ATTACK_OR_BLOCK_LOCK_RE,
    CANT_ATTACK_OR_BLOCK_RE,
    CANT_ATTACK_RE,
    CANT_BE_BLOCKED_RE,
    CANT_BLOCK_AND_CANT_BE_BLOCKED_RE,
    CANT_BLOCK_RE,
    MUST_BE_BLOCKED_BY_ONE_RE,
    MUST_BE_BLOCKED_RE,
    combat_restriction_affects,
    combat_restriction_specs,
)
from .static_conditions import parse_combat_condition, qualified_combat_restriction_specs, static_condition
from .matcher_types import StaticContext, StaticResult, claim

# RULE 508.1a's standalone attack permission ("~ can attack as though it
# didn't have defender.") and the counted multi-block one.
def static_attack_as_though_no_defender(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = ATTACK_AS_THOUGH_NO_DEFENDER_RE.fullmatch(text)
    if m is not None:
        return [EffectSpec("combat_restriction", {
            "kind": "attacks_as_though_no_defender",
            "affects": combat_restriction_affects(m.group("subject")),
        })]
    return None


#: RULE 702.122a / 702.171a: "~ [saddles Mounts and] crews Vehicles as though its power were N greater" (the Pilot
#: token). A creature's contribution to a Crew or Saddle cost, not its power (RULE 208.1), so it rides the
#: ``combat_restriction`` param table as a permission-style kind (``crew_power_bonus`` / ``saddle_power_bonus``).
_CREW_SADDLE_BONUS_RE = re.compile(
    r"~ (?P<saddle>saddles mounts and )?crews vehicles as though its power were (?P<n>\d+) greater",
    re.IGNORECASE,
)


def static_crew_saddle_power_bonus(ctx: StaticContext) -> StaticResult:
    m = _CREW_SADDLE_BONUS_RE.fullmatch(ctx.text)
    if m is None:
        return None
    kinds = ["crew_power_bonus"] + (["saddle_power_bonus"] if m.group("saddle") else [])
    return [EffectSpec("combat_restriction", {"kind": kind, "count": int(m.group("n")), "affects": "self"})
            for kind in kinds]


def static_block_additional_n(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = BLOCK_ADDITIONAL_N_RE.fullmatch(text)
    if m is not None:
        return [EffectSpec("combat_restriction", {
            "kind": "extra_blocks", "count": int(m.group("n")),
            "affects": combat_restriction_affects(m.group("subject")),
        })]
    return None


# Combat-restriction family ("~ can't attack.", "enchanted creature can't
# be blocked.", "~ attacks each combat if able.", …) — see
# `combat_restriction_specs` above. Ordered most-specific-first so a
# combined clause matches its own row rather than a shorter prefix; since
# every branch uses `fullmatch`, a shorter regex simply fails on any
# unconsumed trailing text (fail-closed), so the ordering is for clarity
# rather than correctness.
def static_attack_tax(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = ATTACK_TAX_RE.fullmatch(text)
    if m is not None:
        params: dict[str, object] = {
            "defender_scope": "player_or_planeswalker" if m.group("planeswalkers") else "player",
        }
        if m.group("n") is not None:
            params["amount"] = int(m.group("n"))
        elif m.group("x_source") == "enchantments you control":
            params["amount_count_selector"] = "enchantments_you_control"
        else:
            params["amount_count_selector"] = "basic_land_types_among_lands_you_control"
        return [EffectSpec("attack_tax", params)]
    return None


def static_cant_attack_or_block_lock(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = CANT_ATTACK_OR_BLOCK_LOCK_RE.fullmatch(text)
    if m is not None:
        return claim(combat_restriction_specs(
            m.group("subject"), ["cant_attack", "cant_block"] + (["cant_crew"] if m["crew"] else []), lock=True,
            mana_exception=bool(m.group("mana_exception")),
        ))
    return None


def static_cant_attack_or_block(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = CANT_ATTACK_OR_BLOCK_RE.fullmatch(text)
    if m is not None:
        flags = ["cant_attack", "cant_block"] + (["cant_crew"] if m["crew"] else [])
        return claim(combat_restriction_specs(m.group("subject"), flags))
    return None


def static_cant_block_and_cant_be_blocked(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = CANT_BLOCK_AND_CANT_BE_BLOCKED_RE.fullmatch(text)
    if m is not None:
        return claim(combat_restriction_specs(m.group("subject"), ["cant_block", "cant_be_blocked"]))
    return None


def static_cant_attack(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = CANT_ATTACK_RE.fullmatch(text)
    if m is not None:
        return claim(combat_restriction_specs(m.group("subject"), ["cant_attack"]))
    return None


def static_cant_block(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = CANT_BLOCK_RE.fullmatch(text)
    if m is not None:
        return claim(combat_restriction_specs(m.group("subject"), ["cant_block"]))
    return None


def static_cant_be_blocked(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = CANT_BE_BLOCKED_RE.fullmatch(text)
    if m is not None:
        return claim(combat_restriction_specs(m.group("subject"), ["cant_be_blocked"]))
    return None


def _combat_object_specs(text: str) -> Optional[list[EffectSpec]]:
    """RULE 508/509/510: one subject grammar for all standing combat tails.

    Legacy rows win for their existing shapes. New compositions retain every
    conjunct; neither an unknown condition nor an unknown subject is dropped.
    """
    unquoted = re.sub(r'"[^"]*"', '', text)
    if not re.search(r"\b(?:attacks?|blocks?|blocked|assigns? combat damage)\b", unquoted):
        return None
    m = re.fullmatch(r"(?P<subject>.+?) (?P<tail>(?:attacks?|blocks?|assigns?|can|can\'t|gets?|has|have) .+)", text)
    if m is None:
        return None
    subject, tail = m['subject'], m['tail']
    if subject == '~' or re.fullmatch(ATTACHED_SUBJECT_PATTERN, subject):
        affects = {'affects': combat_restriction_affects(subject)}
    else:
        phrase = re.sub(r'^(?:each|all) ', '', subject)
        selector = object_set(phrase, ClauseReading())
        if selector is None or selector.get('controller_ref') or selector.get('of') == 'context':
            return None
        affects = {'affects': selector}
    condition = None
    conditional = re.fullmatch(r"(?P<body>can'?t (?:attack|block|attack or block)) if (?P<condition>.+)", tail)
    if conditional:
        if affects['affects'] not in ('self', 'attached_permanent'):
            return None  # a per-member condition must never become a source gate
        phrase = conditional['condition']
        if affects['affects'] == 'attached_permanent':
            phrase = re.sub(r"^it(?:'s| is) ", subject + ' is ', phrase)
        # RULE 508.1c: "defending player ..." gates an attack at declaration, the combat vocabulary's job
        # (`_combat_condition_met`) -- the standing-condition reading PAR-313 added would never hold before attackers.
        condition = None if phrase.startswith("defending player ") else static_condition(phrase)
        if condition is None:
            combat_condition = parse_combat_condition(phrase)
            if combat_condition is None:
                return None
            verbs = ['attack', 'block'] if conditional['body'] == "can't attack or block" else [conditional['body'].split()[-1]]
            return [EffectSpec('combat_restriction', {
                'kind': 'cant_' + verb + '_unless',
                'condition': {'kind': 'not', 'condition': combat_condition}, **affects,
            }) for verb in verbs]
        tail = conditional['body']
    operation = combat_tail(tail, temporary=False)
    if operation is not None:
        kind, params = operation
        if kind == 'both_requirements':
            specs = [EffectSpec('grant_keyword', {'keywords': ['attacks_if_able'], **affects}),
                     EffectSpec('combat_restriction', {'kind': 'must_block_if_able', **affects})]
        else:
            specs = [EffectSpec(kind, {**params, **affects})]
        if condition:
            for spec in specs:
                spec.params['active_if'] = condition
        return specs
    # A shared subject may govern several independently understood predicates
    # (Aura pumps, keyword grants, combat permissions). Reparse each entire
    # predicate; a failed half fails the complete sentence closed.
    for connector in (', and ', ' and ', ', '):
        for split in re.finditer(re.escape(connector), tail):
            if tail[:split.start()].count(chr(34)) % 2:
                continue
            left, right = tail[:split.start()], tail[split.end():]
            before = static_effect_specs(subject + ' ' + left)
            if not before:
                continue
            after = static_effect_specs(subject + ' ' + right)
            if after:
                return [*before, *after]
    return None


def static_attacks_if_able(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = ATTACKS_IF_ABLE_RE.fullmatch(text)
    if m is not None:
        return claim(combat_restriction_specs(m.group("subject"), ["attacks_if_able"]))
    return _combat_object_specs(text)


# RULE 509.1c/d combat requirements — "~ must be blocked if able."/"All
# creatures able to block ~ do so." (Lure-shaped).
def static_must_be_blocked(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = MUST_BE_BLOCKED_RE.fullmatch(text)
    if m is not None:
        return claim(combat_restriction_specs(m.group("subject"), ["must_be_blocked"]))
    return None


def static_must_be_blocked_by_one(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = MUST_BE_BLOCKED_BY_ONE_RE.fullmatch(text)
    if m is not None:
        return claim(combat_restriction_specs(m.group("subject"), ["must_be_blocked_by_exactly_one"]))
    return None


def static_all_must_block(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = ALL_MUST_BLOCK_RE.fullmatch(text)
    if m is not None:
        subject = m.group("subject")
        affects = "self" if subject in ("~", "it") else "attached_permanent"
        return [EffectSpec("grant_keyword", {"keywords": ["all_must_block"], "affects": affects})]
    return None


# RULE 509.1b multi-block permissions — "~ can block an additional
# creature each combat."/"~ can block any number of creatures."
def static_block_additional(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = BLOCK_ADDITIONAL_RE.fullmatch(text)
    if m is not None:
        return [EffectSpec("combat_restriction", {
            "kind": "extra_blocks", "count": 1,
            "affects": combat_restriction_affects(m.group("subject")),
        })]
    return None


def static_block_any_number(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = BLOCK_ANY_NUMBER_RE.fullmatch(text)
    if m is not None:
        return [EffectSpec("combat_restriction", {
            "kind": "unlimited_blocks",
            "affects": combat_restriction_affects(m.group("subject")),
        })]
    return None


# …and their *qualified* siblings ("can't be blocked by creatures with
# power 2 or less", "can't attack unless defending player controls an
# Island", "can't attack alone") — tried after the plain flags above,
# which are `fullmatch`ed and so can never swallow a qualifier.
def static_qualified_combat_restriction_specs(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    qualified = qualified_combat_restriction_specs(text)
    if qualified is not None:
        return claim(qualified)
    return None
