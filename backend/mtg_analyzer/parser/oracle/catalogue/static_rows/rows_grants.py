"""Static-ability helpers: rows grants (split from `static_handlers` by PAR-172's method, ENG-59)."""

from __future__ import annotations

import re
from typing import Any
from ...spec import EffectSpec
from ..subgrammars import COLOR_LETTERS
from ..count_phrase import parse_count_phrase
from .anthem_patterns import (
    ANTHEM_RE,
    BURAKOS_SELF_TYPES_RE,
    COMMANDER_CREATURES_QUOTED_GRANT_RE,
    GRANT_RE,
    GROUP_COUNTER_GRANT_RE,
    MULTI_PERMANENT_TYPE_GRANT_RE,
    OPPONENT_CREATURE_ANTHEM_RE,
    QUOTED_GRANT_RE,
    SELF_ANTHEM_PER_OPPONENT_COLOR_PERMANENT_RE,
)
from .object_scope import (
    graveyard_retrace_grant_specs,
    is_vehicle_scope,
    multi_permanent_type_list,
    parse_scope,
    parse_scope_params,
    permanent_scope_params,
    permanent_type_scope,
    qualifier_ok,
    vehicle_scope_params,
)
from .combat_restrictions import combat_restriction_affects
from .keyword_flags import flag_keywords, flag_keywords_and_ward
from .granted_abilities import (
    CANT_BE_BEAMED_UP_RE,
    GRAVEYARD_BEAM_ME_UP_GRANT_RE,
    GRAVEYARD_RETRACE_GRANT_RE,
    HAND_CYCLING_GRANT_RE,
    quoted_ability_grant_effects_list,
    type_addition_params,
)
from .enter_choices import (
    ATTACHED_ANTHEM_KEYWORD_AND_QUOTED_GRANT_RE,
    ATTACHED_DOUBLE_QUOTED_GRANT_RE,
    ATTACHED_KEYWORD_AND_QUOTED_GRANT_RE,
    ATTACHED_LOOK_TOP_AND_QUOTED_GRANT_RE,
    ATTACHED_QUOTED_ANTHEM_GRANT_AND_TYPE_RE,
    ATTACHED_QUOTED_ANTHEM_GRANT_RE,
    ATTACHED_QUOTED_GRANT_AND_TYPE_RE,
    ATTACHED_QUOTED_GRANT_RE,
    ATTACHED_UNTAP_OTHER_PLAYERS_RE,
    ATTACHED_WARD_AND_QUOTED_GRANT_RE,
    CONTROL_GRANT_RE,
    GRAVEYARD_CHOSEN_TYPE_RE,
    GROUP_CHOSEN_TYPE_RE,
    GROUP_GOADED_RE,
    GROUP_TYPE_ADDITION_RE,
    IS_CHOSEN_TYPE_RE,
    SOULBOND_ANTHEM_RE,
    SOULBOND_GRANT_RE,
    SOULBOND_QUOTED_GRANT_RE,
    attached_untap_other_players,
    chosen_type_group_affects,
    type_addition_plural_words,
)
from .self_statics import granted_trigger_doubler
from .matcher_types import DECLINE, StaticContext, StaticResult, claim

def static_control_grant(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    if CONTROL_GRANT_RE.fullmatch(text):
        return [EffectSpec("control_change", {})]
    return None


def static_is_chosen_type(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    if IS_CHOSEN_TYPE_RE.fullmatch(text):
        return [EffectSpec("type_change", {"affects": "self", "add_subtypes_from_source": True})]
    return None


def static_graveyard_chosen_type(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    if GRAVEYARD_CHOSEN_TYPE_RE.fullmatch(text):
        return [EffectSpec("type_change", {
            "affects": "off_battlefield_only",  # no battlefield half at all
            "add_subtypes_from_source": True,
            "off_battlefield": "your_graveyard",
        })]
    return None


def static_group_type_addition(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = GROUP_TYPE_ADDITION_RE.fullmatch(text)
    if m is not None and "chosen" not in text.lower():
        # PAR-142: "creature tokens you control are Squirrels in addition to their other creature types"
        # (Earl of Squirrel), "nontoken creatures you control are Forest lands in addition to their other
        # types" (Ashaya) — the literal-word sibling of the chosen-type row just below.
        params = chosen_type_group_affects(m.group("body"))
        added = type_addition_plural_words(m.group("words"))
        if params is None or added is None:
            return DECLINE
        return [EffectSpec("type_change", {**params, **added})]
    return None


def static_group_chosen_type(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = GROUP_CHOSEN_TYPE_RE.fullmatch(text)
    if m is not None:
        params = chosen_type_group_affects(m.group("body"))
        if params is None:
            return DECLINE
        params["add_subtypes_from_source"] = True
        if m.group("off"):
            params["off_battlefield"] = "cards_you_own"
        return [EffectSpec("type_change", params)]
    return None


#: PAR-242 (Mocking Doppelganger): "other creatures with the same name as ~ are goaded" -- RULE 701.15b goad on a
#: same-name group of any controller; the goader is the static's controller (`continuous.recompute`'s goaded pass).
_SAME_NAME_GOADED_RE = re.compile(r"other creatures with the same name as ~ are goaded", re.IGNORECASE)


def static_group_goaded(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    if _SAME_NAME_GOADED_RE.fullmatch(text):
        selector = parse_count_phrase("other creatures with the same name as ~")
        return None if selector is None else [EffectSpec("goaded", {"affects": selector})]
    m = GROUP_GOADED_RE.fullmatch(text)
    if m is not None:
        params: dict = {"affects": "creatures_opponents_control"}
        if m.group("cmp"):
            params["power_lt_selector" if m.group("cmp") == "less" else "power_gt_selector"] = (
                "source_power"
            )
        return [EffectSpec("goaded", params)]
    return None


def static_soulbond_quoted_grant(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = SOULBOND_QUOTED_GRANT_RE.fullmatch(text)
    if m is not None:
        grants = quoted_ability_grant_effects_list(m.group("inner"))
        if grants is None:
            return DECLINE
        for g in grants:
            g.params["affects"] = "soulbond_pair"
        return claim(grants)
    return None


def static_soulbond_anthem(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = SOULBOND_ANTHEM_RE.fullmatch(text)
    if m is not None:
        specs = [EffectSpec("anthem", {"power": int(m.group("p")),
                                       "toughness": int(m.group("t")),
                                       "affects": "soulbond_pair"})]
        if m.group("kw"):
            keywords = flag_keywords(m.group("kw"))
            if keywords is None:
                return DECLINE
            specs.append(EffectSpec("grant_keyword",
                                    {"keywords": keywords, "affects": "soulbond_pair"}))
        return claim(specs)
    return None


def static_soulbond_grant(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = SOULBOND_GRANT_RE.fullmatch(text)
    if m is not None:
        keywords = flag_keywords(m.group("kw"))
        if keywords is None:
            return DECLINE
        return [EffectSpec("grant_keyword", {"keywords": keywords, "affects": "soulbond_pair"})]
    return None


def static_attached_untap_other_players(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = ATTACHED_UNTAP_OTHER_PLAYERS_RE.fullmatch(text)
    if m is not None:
        return claim(attached_untap_other_players(m))
    return None


def static_attached_quoted_anthem_grant(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = ATTACHED_QUOTED_ANTHEM_GRANT_RE.fullmatch(text)
    if m is not None:
        grants = quoted_ability_grant_effects_list(m.group("inner"))
        if grants is None:
            return DECLINE
        return [
            EffectSpec("anthem", {"power": int(m.group("p")), "toughness": int(m.group("t")),
                                   "affects": "attached_permanent"}),
            *grants,
        ]
    return None


def static_attached_quoted_anthem_grant_and_type(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = ATTACHED_QUOTED_ANTHEM_GRANT_AND_TYPE_RE.fullmatch(text)
    if m is not None:
        grants = quoted_ability_grant_effects_list(m.group("inner"))
        if grants is None:
            return DECLINE
        return [
            EffectSpec("anthem", {"power": int(m.group("p")), "toughness": int(m.group("t")),
                                   "affects": "attached_permanent"}),
            EffectSpec("type_change", {
                "affects": "attached_permanent",
                "add_subtypes": [m.group("subtype").capitalize()],
            }),
            *grants,
        ]
    return None


def static_attached_anthem_keyword_and_quoted_grant(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = ATTACHED_ANTHEM_KEYWORD_AND_QUOTED_GRANT_RE.fullmatch(text)
    if m is not None:
        keywords = flag_keywords(m.group("keywords"))
        grants = quoted_ability_grant_effects_list(m.group("inner"))
        if keywords is None or grants is None:
            return DECLINE
        return [
            EffectSpec("anthem", {"power": int(m.group("p")), "toughness": int(m.group("t")),
                                   "affects": "attached_permanent"}),
            EffectSpec("grant_keyword", {"keywords": keywords, "affects": "attached_permanent"}),
            *grants,
        ]
    return None


def static_attached_keyword_and_quoted_grant(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = ATTACHED_KEYWORD_AND_QUOTED_GRANT_RE.fullmatch(text)
    if m is not None:
        keywords = flag_keywords(m.group("keywords"))
        grants = quoted_ability_grant_effects_list(m.group("inner"))
        if keywords is None or grants is None:
            return DECLINE
        return [
            EffectSpec("grant_keyword", {"keywords": keywords, "affects": "attached_permanent"}),
            *grants,
        ]
    return None


def static_attached_ward_and_quoted_grant(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = ATTACHED_WARD_AND_QUOTED_GRANT_RE.fullmatch(text)
    if m is not None:
        grants = quoted_ability_grant_effects_list(m.group("inner"))
        if grants is None:
            return DECLINE
        return [
            EffectSpec("grant_keyword", {
                "ward_cost": m.group("cost").strip(),
                "affects": "attached_permanent",
            }),
            *grants,
        ]
    return None


def static_attached_double_quoted_grant(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = ATTACHED_DOUBLE_QUOTED_GRANT_RE.fullmatch(text)
    if m is not None:
        first = quoted_ability_grant_effects_list(m.group("first"))
        second = quoted_ability_grant_effects_list(m.group("second"))
        if (
            m.group("first").strip().lower()
            == "you may look at the top card of your library any time"
            and second is not None
        ):
            return [
                EffectSpec("top_library_permission", {
                    "look": True, "requires_attached": True,
                }),
                *second,
            ]
        if first is None or second is None:
            return DECLINE
        return [*first, *second]
    return None


def static_attached_look_top_and_quoted_grant(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = ATTACHED_LOOK_TOP_AND_QUOTED_GRANT_RE.fullmatch(text)
    if m is not None:
        grants = quoted_ability_grant_effects_list(m.group("inner"))
        if grants is None:
            return DECLINE
        # The permission belongs to the Equipment's controller, while its
        # quote grants an ability to the host.  requires_attached keeps the
        # former active only while the Equipment is attached (RULE 301.5),
        # without incorrectly re-sourcing it onto the creature.
        return [
            EffectSpec("top_library_permission", {
                "look": True, "requires_attached": True,
            }),
            *grants,
        ]
    return None


def static_attached_quoted_grant_and_type(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = ATTACHED_QUOTED_GRANT_AND_TYPE_RE.fullmatch(text)
    if m is not None:
        grants = quoted_ability_grant_effects_list(m.group("inner"))
        if grants is None:
            return DECLINE
        return [
            EffectSpec("type_change", {
                "affects": "attached_permanent",
                "add_subtypes": [m.group("subtype").capitalize()],
            }),
            *grants,
        ]
    return None


def static_attached_quoted_grant(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = ATTACHED_QUOTED_GRANT_RE.fullmatch(text)
    if m is not None:
        # PAR-122: "equipped creature has \"if … triggers an additional time\"" (The Masamune)
        # — a granted doubler, held by the attached permanent rather than the Equipment.
        granted_doubler = granted_trigger_doubler(m.group("inner"))
        if granted_doubler is not None:
            return [granted_doubler]
        grants = quoted_ability_grant_effects_list(m.group("inner"))
        if grants is None:
            return DECLINE
        return claim(grants)
    return None


# PAR-72: "~ is also a Cleric, Rogue, Warrior, and Wizard." (Burakos,
# Party Leader) — RULE 205.1b's "in addition to its other types"
# self-grant, reusing the existing `type_change`/``add_subtypes``
# primitive (`ATTACHED_QUOTED_GRANT_AND_TYPE_RE` just above already
# establishes ``add_subtypes`` as a real, engine-checked grant — this
# is its self-scoped, fixed four-type form). A SOLO-1 fixed phrase
# rather than a general "is also a/an `<list>`" grammar: no other
# cached card prints this exact self-referential party-type-grant
# shape.
def static_burakos_self_types(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = BURAKOS_SELF_TYPES_RE.fullmatch(text)
    if m is not None:
        return [EffectSpec("type_change", {
            "affects": "self", "add_subtypes": ["Cleric", "Rogue", "Warrior", "Wizard"],
        })]
    return None


def static_opponent_creature_anthem(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = OPPONENT_CREATURE_ANTHEM_RE.fullmatch(text)
    if m is not None:
        return [EffectSpec("anthem", {
            "power": int(m.group("p")), "toughness": int(m.group("t")),
            "affects": "creatures_opponents_control",
        })]
    return None


def static_self_anthem_per_opponent_color_permanent(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = SELF_ANTHEM_PER_OPPONENT_COLOR_PERMANENT_RE.fullmatch(text)
    if m is not None:
        selector = "permanents_opponents_control_of_color_" + COLOR_LETTERS[m.group("color").lower()]
        return [EffectSpec("anthem", {
            "power": int(m.group("p")), "toughness": int(m.group("t")),
            "power_count": selector, "toughness_count": selector,
            "affects": "self",
        })]
    return None


def static_anthem(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = ANTHEM_RE.fullmatch(text)
    if m is not None:
        if not qualifier_ok(m):
            return DECLINE
        scope = parse_scope(m.group("body"))
        if scope is not None:
            params = parse_scope_params(scope, m)
        elif is_vehicle_scope(m.group("body")):
            # "Vehicles you control get +1/+1 and have vigilance and
            # reach." (Balthier and Fran) — the `ARTIFACT_SUBTYPES`
            # fallback: a Vehicle isn't a creature until crewed, so this
            # must not fall through to `parse_scope`'s ordinary (creature-only)
            # reading, which would wrongly scope the anthem to
            # ``creatures_you_control`` and so exclude every uncrewed
            # Vehicle it's printed to buff.
            params = vehicle_scope_params(m)
        else:
            return DECLINE
        specs = [
            EffectSpec("anthem",
                       {"power": int(m.group("p")), "toughness": int(m.group("t")), **params})
        ]
        if m.group("kw"):  # "… and have <keywords>" tail
            resolved = flag_keywords_and_ward(m.group("kw"))
            if resolved is None:
                return DECLINE  # e.g. a granted landwalk — fail-closed, whole clause
            keywords, ward_cost = resolved
            grant_params = dict(params)
            if keywords:
                grant_params["keywords"] = keywords
            if ward_cost:
                grant_params["ward_cost"] = ward_cost
            specs.append(EffectSpec("grant_keyword", grant_params))
        if m.group("goaded"):
            # The goader is the static's controller (`continuous.recompute`'s goaded pass); same scope as the anthem.
            specs.append(EffectSpec("goaded", dict(params)))
        return claim(specs)
    return None


def static_commander_creatures_quoted_grant(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = COMMANDER_CREATURES_QUOTED_GRANT_RE.fullmatch(text)
    if m is not None:
        grants = quoted_ability_grant_effects_list(m.group("inner"))
        if grants is None:
            return DECLINE
        for g in grants:
            g.params["affects"] = "commander_creatures_you_own"
        return claim(grants)
    return None


def static_quoted_grant(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = QUOTED_GRANT_RE.fullmatch(text)
    if m is not None:
        if not qualifier_ok(m):
            return DECLINE
        scope = parse_scope(m.group("body"))
        if scope is not None:
            scope_params = parse_scope_params(scope, m)
        elif is_vehicle_scope(m.group("body")):
            scope_params = vehicle_scope_params(m)
        else:
            # PAR-3: a bare non-creature scope ("Other enchantments have
            # '…'", Aura Flux) — `parse_scope` deliberately stays creature-only
            # (kept for `ANTHEM_RE`), so a grant family falls back to the
            # permanent-type sibling instead of failing closed.
            word = permanent_type_scope(m.group("body"))
            basic_only = False
            if word is None and re.fullmatch(r"(?:all |each )?basic lands?", m.group("body"), re.IGNORECASE):
                word, basic_only = "land", True  # PAR-109: "Basic lands you control have '{T}: Add …'"
            if word is None:
                return DECLINE
            scope_params = permanent_scope_params(word, m)
            if basic_only:
                scope_params["object_filter"] = {**(scope_params.get("object_filter") or {}), "basic": True}
        grants = quoted_ability_grant_effects_list(m.group("inner"))
        if grants is None:
            return DECLINE
        for g in grants:
            g.params.update(scope_params)
        return claim(grants)
    return None


def static_group_counter_grant(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = GROUP_COUNTER_GRANT_RE.fullmatch(text)
    if m is not None:
        keywords = flag_keywords(m.group("kw"))
        if keywords is None:
            return DECLINE
        return [EffectSpec("grant_keyword", {
            "keywords": keywords,
            "affects": "creatures_you_control",
            "has_counter_kind": "+1/+1",
        })]
    return None


def static_cant_be_beamed_up(ctx: StaticContext) -> StaticResult:
    m = CANT_BE_BEAMED_UP_RE.fullmatch(ctx.text)
    if m is None:
        return None
    affects = combat_restriction_affects(m.group("subject"))
    specs = []
    if m.group("no_untap"):
        specs.append(EffectSpec("no_untap", {"affects": affects}))
    specs.append(EffectSpec("grant_keyword", {"keywords": ["cant_be_beamed_up"], "affects": affects}))
    return claim(specs)


def static_graveyard_beam_me_up_grant(ctx: StaticContext) -> StaticResult:
    m = GRAVEYARD_BEAM_ME_UP_GRANT_RE.fullmatch(ctx.text)
    if m is None:
        return None
    # RULE 702.196a: the granted cost is the card's own mana cost; the source can be named as unable to be returned.
    return claim([EffectSpec("grant_beam_me_up", {
        "main_phase_only": True, "source_cant_be_beamed_up": bool(m.group("self_excluded")),
    })])


def static_graveyard_retrace_grant(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = GRAVEYARD_RETRACE_GRANT_RE.fullmatch(text)
    if m is not None:
        return claim(graveyard_retrace_grant_specs(m.group("filter")))
    return None


def static_multi_permanent_type_grant(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = MULTI_PERMANENT_TYPE_GRANT_RE.fullmatch(text)
    if m is not None:
        card_types = multi_permanent_type_list(m.group("body"))
        if card_types is None:
            return DECLINE
        resolved = flag_keywords_and_ward(m.group("kw"))
        if resolved is None:
            return DECLINE
        keywords, ward_cost = resolved
        params: dict = {"affects": "permanents_you_control", "card_type": card_types}
        if keywords:
            params["keywords"] = keywords
        if ward_cost:
            params["ward_cost"] = ward_cost
        return [EffectSpec("grant_keyword", params)]
    return None


def static_grant(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = GRANT_RE.fullmatch(text)
    if m is not None:
        if not qualifier_ok(m):
            return DECLINE
        scope = parse_scope(m.group("body"))
        if scope is not None:
            scope_params = parse_scope_params(scope, m)
        elif is_vehicle_scope(m.group("body")):
            scope_params = vehicle_scope_params(m)
        else:
            # PAR-3, same fallback as `QUOTED_GRANT_RE` above — "Artifacts
            # you control have hexproof." (Leonin Abunas-shaped).
            word = permanent_type_scope(m.group("body"))
            if word is None:
                return DECLINE
            scope_params = permanent_scope_params(word, m)
        resolved = flag_keywords_and_ward(m.group("kw"))
        if resolved is None:
            return DECLINE
        keywords, ward_cost = resolved
        grant_params = dict(scope_params)
        if keywords:
            grant_params["keywords"] = keywords
        if ward_cost:
            grant_params["ward_cost"] = ward_cost
        return [EffectSpec("grant_keyword", grant_params)]
    return None


def static_hand_cycling_grant(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = HAND_CYCLING_GRANT_RE.fullmatch(text)
    if m is not None:
        params: dict[str, Any] = {"cost": m.group("cost")}
        if m.group("filter"):
            params["card_type"] = m.group("filter").lower()
        return [EffectSpec("grant_cycling_to_hand", params)]
    return None


#: PAR-185: "enchanted land is a 4/2 red Beast creature with trample. It's still a land." (Zendikon cycle, Awaken the
#: Ancient) / "Forests you control are 1/1 green Elf creatures that are still lands." (Ambush Commander) — RULE 205.1b:
#: a layer-4 `type_change` that *adds* creature (and subtypes) with a base P/T, a layer-5 colour set and a layer-6 keyword
#: grant. The retention rider keeps prior types and subtypes (RULE 205.1b), as modeled by additive type changes.
_ANIMATED_LAND_STATIC_RE = re.compile(
    r"(?:enchanted (?P<attached>land|plains|island|swamp|mountain|forest) is|"
    r"(?P<all>all )?(?P<group>lands|plains|islands|swamps|mountains|forests)(?P<you_control> you control)? are) (?:an? )?"
    r"(?P<p>\d+)/(?P<t>\d+) (?P<words>(?:[a-z-]+ )*?)creatures?"
    r"(?: with (?P<kw>[a-z0-9{}, ]+?))?"
    r"(?:\. it'?s still a land| that'?s still a land| that are still lands|\. they'?re still lands)?\.?",
    re.IGNORECASE,
)
_ANIMATED_LAND_GROUP_AFFECTS = {
    "plains": "plains", "islands": "island", "swamps": "swamp", "mountains": "mountain", "forests": "forest",
}


def static_animated_land(ctx: StaticContext) -> StaticResult:
    m = _ANIMATED_LAND_STATIC_RE.fullmatch(ctx.text.strip())
    if m is None:
        return None
    # The group form's reminder is the "that are still lands" relative clause, the attached form's a sentence.
    if (m.group("group") is None) == (m.group("attached") is None):
        return None
    words = m.group("words").lower().split()
    colors: list[str] = []
    while words and words[0] in COLOR_LETTERS and words[0] != "colorless":
        colors.append(COLOR_LETTERS[words.pop(0)])
        if words and words[0] == "and":
            words.pop(0)
    type_params = type_addition_params(" ".join(words)) if words else {}
    if type_params is None:
        return DECLINE
    type_params = {
        **type_params,
        "add_types": ["creature", *type_params.get("add_types", [])],
        "power": int(m.group("p")), "toughness": int(m.group("t")),
    }
    if m.group("attached"):
        affects = "attached_permanent"
    else:
        group = m.group("group").lower()
        subtype = _ANIMATED_LAND_GROUP_AFFECTS.get(group)
        if m.group("you_control"):
            affects = f"lands_you_control_of_type_{subtype}" if subtype else "lands_you_control"
        else:
            affects = ({"zone": "battlefield", "of": "any", "filter": {"card_type": "land", "subtype": subtype}}
                       if subtype else "all_lands")
    specs = [EffectSpec("type_change", {"affects": affects, **type_params})]
    if colors:
        specs.append(EffectSpec("color", {"affects": affects, "colors": colors, "set": True}))
    if m.group("kw"):
        resolved = flag_keywords_and_ward(m.group("kw"))
        if resolved is None:
            return DECLINE
        keywords, ward_cost = resolved
        specs.append(EffectSpec("grant_keyword", {"affects": affects, "keywords": keywords,
                                **({"ward_cost": ward_cost} if ward_cost else {})}))
    return specs
