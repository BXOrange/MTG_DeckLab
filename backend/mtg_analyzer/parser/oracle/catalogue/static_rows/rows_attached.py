"""Static-ability helpers: rows attached (split from `static_handlers` by PAR-172's method, ENG-59)."""

from __future__ import annotations

from typing import Any, Optional
from ...spec import EffectSpec
from ..clause_primitives import split_keywords_with_parametric
from ..subgrammars import devotion_selector
from ..count_phrase import parse_amount_phrase, parse_count_phrase
from ..clause_hooks import static_effect_specs
from .object_scope import parse_scope, parse_scope_params
from .keyword_flags import flag_keywords, flag_keywords_and_ward
from .granted_abilities import (
    ATTACHED_ANTHEM_PROTECTION_RE,
    ATTACHED_ANTHEM_RE,
    ATTACHED_GOADED_RE,
    ATTACHED_GRANT_RE,
    ATTACHED_PROTECTION_RE,
    ATTACHED_REMOVE_KEYWORD_RE,
    ATTACHED_TRAILING_TYPE_RE,
    ATTACHED_TYPE_ADDITION_RE,
    GROUP_ANTHEM_PROTECTION_RE,
    GROUP_PROTECTION_RE,
    SELF_PROTECTION_RE,
    attached_type_addition,
    protection_params,
    type_addition_params,
)
from .self_statics import (
    ANTHEM_DEVOTION_SELF_RE,
    ATTACHED_ANTHEM_FOR_EACH_RE,
    ATTACHED_ANTHEM_X_RE,
    SELF_ANTHEM_FOR_EACH_GY_SUBTYPE_RE,
    SELF_ANTHEM_FOR_EACH_RE,
    SELF_ANTHEM_RE,
    SELF_GRANT_RE,
    for_each_count_selector,
    self_permission_spec,
)
from .matcher_types import DECLINE, StaticContext, StaticResult, claim

# RULE 702.16 standing protection grants — before every anthem/
# keyword-grant family below, whose `flag_keywords` would reject
# "protection from <quality>" (not a flag keyword) and fail the clause
# closed. Compound "+N/+N and protection" first, since the bare forms
# are prefixes of it.
def static_attached_anthem_protection(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = ATTACHED_ANTHEM_PROTECTION_RE.fullmatch(text)
    if m is not None:
        params = protection_params(m.group("quality"))
        if params is None:
            return DECLINE
        if m.group("exempt"):
            params["exempt_own_attachment"] = True
        return [
            EffectSpec("anthem", {"power": int(m.group("p")), "toughness": int(m.group("t")),
                                   "affects": "attached_permanent"}),
            EffectSpec("grant_protection_static",
                       {"affects": "attached_permanent", **params}),
        ]
    return None


def static_group_anthem_protection(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = GROUP_ANTHEM_PROTECTION_RE.fullmatch(text)
    if m is not None:
        scope = parse_scope(m.group("body"))
        if scope is None:
            return DECLINE
        params = protection_params(m.group("quality"))
        if params is None:
            return DECLINE
        scoped = parse_scope_params(scope, m)
        return [
            EffectSpec("anthem", {"power": int(m.group("p")), "toughness": int(m.group("t")),
                                   **scoped}),
            EffectSpec("grant_protection_static", {**scoped, **params}),
        ]
    return None


def static_self_protection(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = SELF_PROTECTION_RE.fullmatch(text)
    if m is not None:
        params = protection_params(m.group("quality"))
        if params is None:
            return DECLINE
        return [EffectSpec("grant_protection_static", {"affects": "self", **params})]
    return None


def static_attached_protection(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = ATTACHED_PROTECTION_RE.fullmatch(text)
    if m is not None:
        params = protection_params(m.group("quality"))
        if params is None:
            return DECLINE
        if m.group("exempt"):
            params["exempt_own_attachment"] = True
        return [EffectSpec("grant_protection_static", {"affects": "attached_permanent", **params})]
    return None


def static_group_protection(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = GROUP_PROTECTION_RE.fullmatch(text)
    if m is not None:
        scope = parse_scope(m.group("body"))
        if scope is None:
            return DECLINE
        params = protection_params(m.group("quality"))
        if params is None:
            return DECLINE
        return [EffectSpec("grant_protection_static", {**parse_scope_params(scope, m), **params})]
    return None


# PAR-43: "equipped/enchanted <subject> gets +N/+N for each <X> [and has
# <keywords>]" — the attached-permanent sibling of the self-scoped
# `SELF_ANTHEM_FOR_EACH_RE` row below, tried first for the same reason
# that row precedes `SELF_ANTHEM_RE`: `ATTACHED_ANTHEM_RE`'s
# fixed-digit pattern would otherwise claim the "+1/+1" prefix and drop
# the "for each …" scaling.
def static_attached_anthem_for_each(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = ATTACHED_ANTHEM_FOR_EACH_RE.fullmatch(text)
    if m is not None:
        what = m.group("what").strip().lower()
        selector = for_each_count_selector(what, self_form=False)
        if selector is not None:
            specs = [EffectSpec("anthem", {
                "affects": "attached_permanent",
                "power": int(m.group("p")), "toughness": int(m.group("t")),
                "power_count": selector, "toughness_count": selector,
            })]
            if m.group("kw"):  # "… and has <keywords>" tail
                keywords = flag_keywords(m.group("kw"))
                if keywords is None:
                    return DECLINE  # fail-closed, whole clause
                specs.append(EffectSpec("grant_keyword", {"keywords": keywords,
                                                            "affects": "attached_permanent"}))
            return claim(specs)
    return None


    # A "for each …" quantity with no wired selector — fail closed, same
    # as the self-scoped row (never silently apply +0).

# Attached-permanent keyword removal ("equipped creature gets +3/+3 and
# loses flying" / "enchanted creature loses flying").
def static_attached_remove_keyword(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = ATTACHED_REMOVE_KEYWORD_RE.fullmatch(text)
    if m is not None:
        keywords = flag_keywords(m.group("kw"))
        if keywords is None:
            return DECLINE
        specs: list[EffectSpec] = []
        if m.group("p") is not None:
            specs.append(EffectSpec("anthem", {
                "power": int(m.group("p")), "toughness": int(m.group("t")),
                "affects": "attached_permanent",
            }))
        specs.append(EffectSpec("remove_keyword", {
            "keywords": keywords, "affects": "attached_permanent",
        }))
        return claim(specs)
    return None


def static_attached_type_addition(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = ATTACHED_TYPE_ADDITION_RE.fullmatch(text)
    if m is not None:
        return claim(attached_type_addition(m))
    return None


# PAR-142: a second sentence that only adds a type to the host — "Enchanted creature gets +1/+1 and has
# flying, haste, and "{1}: ~ gets +1/+0 until end of turn." **It's a Dragon in addition to its other
# types.**" (Draconic Destiny). The first sentence is an ordinary attached grant; "it" is the host.
def static_attached_trailing_type(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    trailing = ATTACHED_TRAILING_TYPE_RE.fullmatch(text)
    if trailing is not None:
        head = static_effect_specs(trailing.group("main"))
        added = type_addition_params(trailing.group("words"))
        if head and added is not None and not added.get("legendary"):
            return [*head, EffectSpec("type_change", {"affects": "attached_permanent", **added})]
    return None


# Attached-permanent shape first ("equipped creature gets +2/+2 [and has
# <keywords>]") — a closed subject list, so this never competes with the
# "you control" scopes below (singular "gets"/"has" vs. their plural
# "get"/"have"). `affects="attached_permanent"` is honoured by both
# `anthem` (layer 7c) and `grant_keyword` (layer 6) in `game/continuous.py`.
def static_attached_anthem(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = ATTACHED_ANTHEM_RE.fullmatch(text)
    if m is not None:
        specs = [
            EffectSpec("anthem", {"power": int(m.group("p")), "toughness": int(m.group("t")),
                                   "affects": "attached_permanent"})
        ]
        if m.group("kw"):  # "… and has <keywords>" tail
            resolved = flag_keywords_and_ward(m.group("kw"))
            if resolved is None:
                return DECLINE  # e.g. a granted landwalk — fail-closed, whole clause
            keywords, ward_cost = resolved
            params: dict = {"affects": "attached_permanent"}
            if keywords:
                params["keywords"] = keywords
            if ward_cost:
                params["ward_cost"] = ward_cost
            specs.append(EffectSpec("grant_keyword", params))
        if m.group("goaded"):  # "… and is goaded" tail (RULE 701.15b)
            specs.append(EffectSpec("goaded", {"affects": "attached_permanent"}))
        if m.group("every_type"):  # "… and is every creature type" tail (RULE 702.73a)
            specs.append(EffectSpec("type_change", {
                "affects": "attached_permanent", "add_subtypes": ["Changeling"],
            }))
        return claim(specs)
    return None


# Attached-permanent keyword-only grant ("equipped creature has trample",
# "enchanted creature has indestructible and is goaded", "… has ward {2}").
def static_attached_grant(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = ATTACHED_GRANT_RE.fullmatch(text)
    if m is not None:
        resolved = flag_keywords_and_ward(m.group("kw"))
        if resolved is None:
            return DECLINE
        keywords, ward_cost = resolved
        if m.group("must_be_blocked"):
            keywords = [*keywords, "must_be_blocked"]
        params = {"affects": "attached_permanent"}
        if keywords:
            params["keywords"] = keywords
        if ward_cost:
            params["ward_cost"] = ward_cost
        specs = [EffectSpec("grant_keyword", params)]
        if m.group("goaded"):
            specs.append(EffectSpec("goaded", {"affects": "attached_permanent"}))
        return claim(specs)
    return None


# The bare "enchanted creature is goaded." (RULE 701.15b) — no other
# grant on the Aura at all.
def static_attached_goaded(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = ATTACHED_GOADED_RE.fullmatch(text)
    if m is not None:
        return [EffectSpec("goaded", {"affects": "attached_permanent"})]
    return None


# "~ gets +X/+X, where X is your devotion to <colour(s)/wedge/hybrid>."
# (RULE 202.2f/700.6, Blended Twistling-shaped) — a standing, self-
# scoped anthem whose amount is `continuous.count_selector`'s
# `devotion_to_<key>` vocabulary, tried before `SELF_ANTHEM_RE`
# (fixed-digit only) since "x" would never match that row's ``\d+``.
# PAR-30: "~ gets +P/+T for each `<subtype>` card in your graveyard"
# (Katara, Seeking Revenge). Tried before `SELF_ANTHEM_RE` since that
# row's `[+-]\d+/[+-]\d+` would claim the "+1/+1" prefix and drop the
# "for each …" scaling.
def static_attached_anthem_x(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = ATTACHED_ANTHEM_X_RE.fullmatch(text)
    if m is not None and any(value.endswith("x") for value in (m.group("p"), m.group("t"))):

        what = m.group("what").strip()
        # RULE 301.5a: "its" refers to the host, while ~ names the Equipment.
        selector = "affected_mana_value" if what == "its mana value" else parse_amount_phrase(what)
        if selector is None:
            return None if m.group("subject") == "~" else DECLINE
        if isinstance(selector, dict) and "terms" in selector and " on it" in what:
            return DECLINE  # Compound pronouns require per-term referent tracking.
        if isinstance(selector, dict) and selector.get("counters_on") == "source" and what.endswith(" on it"):
            selector = {**selector, "counters_on": "affected"}
        params = {"affects": "self" if m.group("subject") == "~" else "attached_permanent"}
        for axis, group in (("power", "p"), ("toughness", "t")):
            value = m.group(group)
            params[axis] = (-1 if value.startswith("-") else 1) if value.endswith("x") else int(value)
            if value.endswith("x"):
                params[axis + "_count"] = selector
        return [EffectSpec("anthem", params)]
    return None


def static_self_anthem_for_each_gy_subtype(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = SELF_ANTHEM_FOR_EACH_GY_SUBTYPE_RE.fullmatch(text)
    if m is not None:

        selector = parse_count_phrase(f"{m.group('sub').lower()} cards in your graveyard")
        if selector is not None:
            return [EffectSpec("anthem", {
                "affects": "self",
                "power": int(m.group("p")), "toughness": int(m.group("t")),
                "power_count": selector, "toughness_count": selector,
            })]
    return None


# PAR-43: "~ gets +P/+T for each <X>" — general standing self-anthem
# whose per-unit +P/+T scales by a `continuous.count_selector` value.
def static_self_anthem_for_each(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = SELF_ANTHEM_FOR_EACH_RE.fullmatch(text)
    if m is not None:
        what = m.group("what").strip().lower()
        selector = for_each_count_selector(what, self_form=True)
        if selector is not None:
            return [EffectSpec("anthem", {
                "affects": "self",
                "power": int(m.group("p")), "toughness": int(m.group("t")),
                "power_count": selector, "toughness_count": selector,
            })]
    return None


    # A "for each …" quantity with no wired selector — fail closed
    # (an anthem reading an unmodeled count would silently apply +0).
def static_anthem_devotion_self(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = ANTHEM_DEVOTION_SELF_RE.fullmatch(text)
    if m is not None:
        selector = devotion_selector(m)
        if selector:
            # ``power``/``toughness`` are the *per-unit* amount `_pt_mod_
            # count` multiplies by the count selector's value (RULE
            # 202.2f's "+X/+X" is 1 per point of devotion, not a flat 0).
            return [EffectSpec("anthem", {
                "affects": "self", "power": 1, "toughness": 1,
                "power_count": selector, "toughness_count": selector,
            })]
    return None


# Self-scoped anthem/grant ("~ gets +2/+2 and has flying", "~ has
# trample [and can attack as though it didn't have defender]") — the
# inner half of nearly every RULE 613.6 conditional.
def static_self_anthem(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = SELF_ANTHEM_RE.fullmatch(text)
    if m is not None:
        specs = [
            EffectSpec("anthem", {"power": int(m.group("p")), "toughness": int(m.group("t")),
                                   "affects": "self"})
        ]
        keywords: Optional[list[str]] = None
        if m.group("kw"):
            keywords = flag_keywords(m.group("kw"))
            if keywords is None:
                return DECLINE
        if m.group("attacks_if_able"):
            keywords = (keywords or []) + ["attacks_if_able"]
        if keywords:
            specs.append(EffectSpec("grant_keyword", {"keywords": keywords, "affects": "self"}))
        tail = self_permission_spec(m)
        if tail is False:
            return DECLINE
        if tail is not None:
            specs.append(tail)
        return claim(specs)
    return None


def static_self_grant(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = SELF_GRANT_RE.fullmatch(text)
    if m is not None:
        kw_text = m.group("kw")
        keywords = flag_keywords(kw_text)
        parametric: list[dict[str, object]] = []
        if keywords is None:
            # ENG-31: "~ has firebending N …" (Fire Nation Cadets) — only
            # reached when `flag_keywords` fails, so the ordinary
            # landwalk/flag path is untouched.
            split = split_keywords_with_parametric(kw_text)
            if split is None:
                return DECLINE
            keywords, parametric = split
        if not keywords and not parametric:
            return DECLINE
        params: dict[str, Any] = {"affects": "self"}
        if keywords:
            params["keywords"] = keywords
        if parametric:
            params["parametric_keywords"] = parametric
        specs = [EffectSpec("grant_keyword", params)]
        tail = self_permission_spec(m)
        if tail is False:
            return DECLINE
        if tail is not None:
            specs.append(tail)
        return claim(specs)
    return None
