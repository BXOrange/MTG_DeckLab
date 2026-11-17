"""Static-ability helpers: rows self and cost (split from `static_handlers` by PAR-172's method, ENG-59)."""

from __future__ import annotations

import re
from ...spec import EffectSpec
from ..subgrammars import CANT_BE_COUNTERED_RE
from ..clause_hooks import static_effect_specs, trigger_condition_dict
from ..subtype_vocabulary import SUBTYPES
from ..trigger_doubler import parse_trigger_doubler
from .anthem_patterns import (
    PT_CDA_RE,
    PT_CDA_SINGLE_RE,
    PT_CDA_THAT_NUMBER_RE,
    TURN_SPLIT_FIXED_PT_RE,
    TURN_SPLIT_PT_RE,
    pt_cda_selector,
)
from .object_scope import scoped_group_selector
from .keyword_flags import (
    BASIC_LAND_TYPE_LIST,
    FLASH_PERMISSION_RE,
    GRANT_CANT_BE_COUNTERED_RE,
    GRANT_SEARCH_PROHIBITED_RE,
    GRANT_SKIP_EXTRA_TURNS_RE,
    LANDS_EVERY_BASIC_TYPE_RE,
    flag_keywords,
    flag_keywords_and_ward,
    flash_permission_filter,
)
from .cost_patterns import DURING_OTHER_TURNS_COST_RE, SELF_GRAVEYARD_SHUFFLE_RE
from .granted_abilities import quoted_ability_grant_effects_list
from .self_statics import conditional_static_specs, extra_etb_counter_specs
from .matcher_types import DECLINE, StaticContext, StaticResult, claim

#: RULE 110.1 — a "permanent spell" is a spell of any of these types (the Defilers' filter).
_PERMANENT_SPELL_TYPES = ("creature", "artifact", "enchantment", "land", "planeswalker", "battle")
_COLOR_LETTERS = {"white": "W", "blue": "U", "black": "B", "red": "R", "green": "G"}
_PIP_LIFE_OPTION_RE = re.compile(
    r"as an additional cost to cast (?P<c>white|blue|black|red|green) permanent spells, you may pay 2 life\. "
    r"those spells cost (?P<pip>\{[wubrg]\}) less to cast if you paid life this way\. "
    r"this effect reduces only the amount of (?P<c2>white|blue|black|red|green) mana you pay"
)


def static_fixed_base(ctx: StaticContext) -> StaticResult:
    fixed = re.fullmatch(
        r"(?P<subject>creatures(?: you control| your opponents control)?|~|enchanted creature|equipped creature) "
        r"(?:has|have) base power and toughness (?P<p>\d+)/(?P<t>\d+)"
        r"(?: and (?:has|have) (?P<keywords>.+))?", ctx.text, re.IGNORECASE,
    )
    if fixed is None:
        return None
    affects = {'creatures': scoped_group_selector('any', {'card_type': 'creature'}),
               'creatures you control': scoped_group_selector('you', {'card_type': 'creature'}),
               'creatures your opponents control': scoped_group_selector('opponents', {'card_type': 'creature'}),
               '~': 'self',
               'enchanted creature': 'attached_permanent', 'equipped creature': 'attached_permanent'}[fixed['subject']]
    # RULE 613.4b: base P/T is set before ordinary pumps and counters.
    specs = [EffectSpec('pt_set', {'affects': affects, 'power': int(fixed['p']), 'toughness': int(fixed['t'])})]
    if fixed['keywords']:
        keywords = flag_keywords_and_ward(fixed['keywords'])
        if keywords is None:
            return None
        words, ward = keywords
        specs.append(EffectSpec('grant_keyword', {'affects': affects, 'keywords': words,
                                                 **({'ward_cost': ward} if ward else {})}))
    return specs


# RULE 702.152: a grant, a cost adjustment, and a restricted zone permission.
def static_match(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    match = re.fullmatch(r"each creature spell you cast with mana value (\d+) or greater has blitz\. the blitz cost is equal to its mana cost", text)
    if match:
        return [EffectSpec("grant_blitz", {"min_mana_value": int(match.group(1))})]
    return None


def static_blitz_cost_reduction(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    if text == "blitz costs you pay cost {1} less for each time you've cast your commander from the command zone this game":
        return [EffectSpec("blitz_cost_reduction", {"amount": 1})]
    return None


def static_blitz_graveyard_permission(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    if text in {"you may cast ~ from your graveyard using its blitz ability",
                "you may cast this card from your graveyard using its blitz ability"}:
        return [EffectSpec("blitz_graveyard_permission", {})]
    return None


def static_match_2(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    match = re.fullmatch(r"creature spells you cast from your hand have blitz ((?:\{[^}]+\})+)", text)
    if match:
        return [EffectSpec("grant_blitz", {"from_hand": True, "cost": match.group(1)})]
    return None


# The Defilers (RULE 601.2b/118.8): one coloured pip of a coloured permanent spell may be paid with 2 life instead.
def static_pip_life_option(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    defiler = _PIP_LIFE_OPTION_RE.fullmatch(text)
    if defiler is not None and defiler.group("c") == defiler.group("c2"):
        letter = _COLOR_LETTERS[defiler.group("c")]
        if defiler.group("pip") == "{" + letter.lower() + "}":
            return [EffectSpec("pip_life_option", {
                "color": letter, "pips": 1, "spell_color": letter, "spell_type": list(_PERMANENT_SPELL_TYPES),
            })]
    return None


def static_storm_grant(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    if text == "instant and sorcery spells you cast have storm":
        return [EffectSpec("grant_keyword", {
            "affects": "instant_sorcery_spells_you_cast", "keywords": ["storm"],
        })]
    return None


# "During turns other than yours, spells you cast cost {1} less to cast." (Geyser Drake, Naiad of Hidden Coves) — a
# cost discount gated by RULE 613.6's `not_your_turn`, the same `active_if` a condition-gated static carries.
def static_during_other_turns_cost(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    other_turns = DURING_OTHER_TURNS_COST_RE.fullmatch(text)
    if other_turns is not None:
        inner = static_effect_specs(other_turns.group("rest"))
        if inner is not None and all(spec.type == "cost_reduction" for spec in inner):
            return [
                EffectSpec(spec.type, {**spec.params, "active_if": {"kind": "not_your_turn"}}, condition=spec.condition)
                for spec in inner
            ]
    return None


def static_trigger_doubler(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    if text.lower().startswith("if ") and "triggers an additional time" in text.lower():

        doubler = parse_trigger_doubler(text, trigger_condition_dict)
        if doubler is not None:
            return [doubler]
    return None


def static_extra_etb_counter_specs(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    extra_counter = extra_etb_counter_specs(text)
    if extra_counter is not None:
        return claim(extra_counter)
    return None


def static_self_graveyard_shuffle(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    if SELF_GRAVEYARD_SHUFFLE_RE.fullmatch(text):
        return [EffectSpec("grant_graveyard_to_library_replacement", {"affects": "self"})]
    return None


def static_commander_damage_triple(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    if re.fullmatch(
        r"if an opponent would be dealt commander damage, they receive triple that amount of commander damage instead",
        text, re.IGNORECASE,
    ):
        return [EffectSpec("commander_damage_multiplier", {"multiplier": 3})]
    return None


# ``additional`` is semantic emphasis for an additive P/T modifier, not
# a different layer operation: "White creatures get an additional
# +1/+1" is simply another ordinary anthem.
def static_fold_additional(text: str) -> str:
    return re.sub(r"\b(gets?) an additional\s+", r"\1 ", text, flags=re.IGNORECASE)


# PAR-50 / RULE 510.1c: combat-damage *assignment* replacements are not
# characteristics, so they ride the existing combat-restriction metadata
# bucket.  The engine consumes these two kinds at the assignment point,
# where blockers and the defending player are actually known.
def static_damage_as_unblocked(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    if re.fullmatch(
        r"you may have ~ assign its combat damage as though it weren'?t blocked",
        text, re.IGNORECASE,
    ):
        return [EffectSpec("combat_restriction", {
            "kind": "damage_as_unblocked", "affects": "self",
        })]
    return None


def static_toughness_damage(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    toughness_damage = re.fullmatch(
        r"(?P<scope>each creature you control|each creature) assigns combat damage equal to its toughness rather than its power",
        text, re.IGNORECASE,
    )
    if toughness_damage is not None:
        return [EffectSpec("combat_restriction", {
            "kind": "damage_uses_toughness",
            "affects": scoped_group_selector(
                "you" if toughness_damage.group("scope").lower() == "each creature you control" else "any",
                {"card_type": "creature"},
            ),
        })]
    return None


# A compositional self-lord: reuse the normal parser for the tail rather
# than maintaining an ever-growing list of ``+N/+N and <thing>``
# combinations.  Besides keywords this admits independently modelled
# self statics such as protection or combat restrictions, and the outer
# conditional wrapper below applies one live gate to every emitted spec.
def static_compound_self(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    compound_self = re.fullmatch(
        r"~ gets \+(?P<p>\d+)/\+(?P<t>\d+) and (?P<tail>.+)", text, re.IGNORECASE
    )
    if compound_self is not None:
        tail_specs = static_effect_specs("~ " + compound_self.group("tail"))
        if tail_specs:
            return [EffectSpec("anthem", {
                "power": int(compound_self.group("p")),
                "toughness": int(compound_self.group("t")),
                "affects": "self",
            }), *tail_specs]
    return None


# The quoted-ability sibling of the preceding composition.  The nested
# helper already validates and builds triggers/activated abilities; only
# its temporary attachment-relative scope changes to the receiving
# permanent's self scope here.  An optional colour clause is the same
# ordinary layer-5 static, not a threshold- or tribe-specific effect.
def static_quoted_tail(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    quoted_tail = re.fullmatch(
        r"~ gets \+(?P<p>\d+)/\+(?P<t>\d+)(?:, is (?P<color>white|blue|black|red|green))?"
        r",? and has \"(?P<inner>.+)\"", text, re.IGNORECASE,
    )
    if quoted_tail is not None:
        grants = quoted_ability_grant_effects_list(quoted_tail.group("inner"))
        if grants:
            specs = [EffectSpec("anthem", {
                "power": int(quoted_tail.group("p")),
                "toughness": int(quoted_tail.group("t")), "affects": "self",
            })]
            if quoted_tail.group("color"):
                specs.append(EffectSpec("color_change", {
                    "colors": [quoted_tail.group("color")], "affects": "self",
                }))
            for grant in grants:
                params = dict(grant.params)
                params["affects"] = "self"
                specs.append(EffectSpec(grant.type, params, condition=grant.condition))
            return claim(specs)
    return None


# The same layer composition with a keyword between the colour and quote
# is common in ordinary continuous effects too.  Each component remains a
# normal generic EffectSpec, so condition wrappers and group scopes keep
# working without a bespoke combined ability.
def static_flag_keywords(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    colored_keyword_quoted_tail = re.fullmatch(
        r"~ gets \+(?P<p>\d+)/\+(?P<t>\d+), is (?P<color>white|blue|black|red|green), "
        r"has (?P<keywords>.+?), and has \"(?P<inner>.+)\"", text, re.IGNORECASE,
    )
    if colored_keyword_quoted_tail is not None:
        keywords = flag_keywords(colored_keyword_quoted_tail.group("keywords"))
        grants = quoted_ability_grant_effects_list(colored_keyword_quoted_tail.group("inner"))
        if keywords and grants:
            specs = [
                EffectSpec("anthem", {
                    "power": int(colored_keyword_quoted_tail.group("p")),
                    "toughness": int(colored_keyword_quoted_tail.group("t")), "affects": "self",
                }),
                EffectSpec("color_change", {
                    "colors": [colored_keyword_quoted_tail.group("color")], "affects": "self",
                }),
                EffectSpec("grant_keyword", {"keywords": keywords, "affects": "self"}),
            ]
            for grant in grants:
                params = dict(grant.params)
                params["affects"] = "self"
                specs.append(EffectSpec(grant.type, params, condition=grant.condition))
            return claim(specs)
    return None


# Colour-setting and an acquired quoted ability are independent layer-5
# and layer-6 operations.  Keep this compositional for any permanent,
# rather than baking a card's particular threshold wording into the
# catalogue.
def static_colored_quoted_self(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    colored_quoted_self = re.fullmatch(
        r'~ is (?P<color>white|blue|black|red|green),? and has "(?P<inner>.+)"',
        text, re.IGNORECASE,
    )
    if colored_quoted_self is not None:
        grants = quoted_ability_grant_effects_list(colored_quoted_self.group("inner"))
        if grants:
            specs = [EffectSpec("color_change", {
                "colors": [colored_quoted_self.group("color")], "affects": "self",
            })]
            for grant in grants:
                params = dict(grant.params)
                params["affects"] = "self"
                specs.append(EffectSpec(grant.type, params, condition=grant.condition))
            return claim(specs)
    return None


# The no-P/T sibling: a conditional/static source may itself acquire one
# quoted trigger or activation.  This uses precisely the same recursive
# quoted-ability catalog as group grants; the sole difference is that the
# recipient is the source permanent.
def static_quoted_self(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    quoted_self = re.fullmatch(r'~ has "(?P<inner>.+)"', text, re.IGNORECASE)
    if quoted_self is not None:
        grants = quoted_ability_grant_effects_list(quoted_self.group("inner"))
        if grants:
            specs = []
            for grant in grants:
                params = dict(grant.params)
                params["affects"] = "self"
                specs.append(EffectSpec(grant.type, params, condition=grant.condition))
            return claim(specs)
    return None


# RULE 604.3 + 613.6: a CDA split by whose turn it is (Angry Mob) — two
# sentences, each a self P/T definition gated on the opposite turn.
def static_turn_split_pt(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    turn_halves = TURN_SPLIT_PT_RE.fullmatch(text)
    if turn_halves is not None:
        first = static_effect_specs(turn_halves.group("first"))
        second = static_effect_specs(turn_halves.group("second"))
        if first and second and first[0].type == "pt_cda" and second[0].type == "pt_set":
            return claim(first + second)
        return DECLINE
    return None


def static_turn_split_fixed_pt(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    turn_split = TURN_SPLIT_FIXED_PT_RE.fullmatch(text)
    if turn_split is not None:
        n = int(turn_split.group("n"))
        return [EffectSpec("pt_set", {
            "affects": "self", "power": n, "toughness": n,
            "active_if": {"kind": "not_your_turn"},
        })]
    return None


#: Sentence boundary in front of a further "as long as ...", the only join the run above accepts.
_AS_LONG_AS_SENTENCE_SPLIT_RE = re.compile(r"(?<=\.) (?=as long as )", re.I)

# RULE 613.6: "as long as <condition>, <static>" (either printed order) —
# parse the gate, then re-enter with the bare static and hand every spec
# it returns the same ``active_if``. Done *first*, so no unconditional
# row can claim a conditional clause by matching a prefix of it, and
# recursion-guarded: the inner clause is strictly shorter, and a second
# "as long as" inside it fails the whole line closed (see
# `AS_LONG_AS_TRAILING_RE`).
def static_conditional_static_specs(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    conditional = conditional_static_specs(text)
    if conditional is not None:
        return claim(conditional)
    # PAR-318 / RULE 604.3 + 613.6: a run of whole "as long as <cond>, <static>." sentences on one line (Gaea's Liege:
    # its power and toughness follow one count while it is not attacking, another while it is). Each sentence is its own
    # gated static; one that fails to parse fails the whole line closed.
    sentences = _AS_LONG_AS_SENTENCE_SPLIT_RE.split(text)
    if len(sentences) > 1:
        specs: list = []
        for sentence in sentences:
            part = conditional_static_specs(sentence if sentence.endswith(".") else sentence + ".")
            if part is None:
                return DECLINE
            specs.extend(part)
        return claim(specs)
    return None


# RULE 604.3 characteristic-defining P/T — "~'s power and toughness are
# each equal to the number of <X>."  (see `PT_CDA_RE`).
def static_pt_cda(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = PT_CDA_RE.fullmatch(text)
    if m is not None:
        selector = pt_cda_selector(m.group("what").strip().rstrip("."))
        if selector is None:
            return DECLINE  # fail-closed — an unwhitelisted quantity phrase
        return [EffectSpec("pt_cda", {
            "affects": "self",
            "power_count": selector,
            "toughness_count": selector,
        })]
    return None


# Lhurgoyf and its relatives reuse the power's count for toughness with
# an offset. Both values remain characteristic-defining (RULE 604.3).
def static_pt_cda_that_number(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = PT_CDA_THAT_NUMBER_RE.fullmatch(text)
    if m is not None:
        selector = pt_cda_selector(m.group("what").strip())
        if selector is None:
            return DECLINE
        return [EffectSpec("pt_cda", {
            "affects": "self", "power_count": selector,
            "toughness_count": {"terms": [selector], "plus": int(m.group("plus"))},
        })]
    return None


def static_pt_cda_single(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = PT_CDA_SINGLE_RE.fullmatch(text)
    if m is not None:
        selector = pt_cda_selector(m.group("what").strip().rstrip("."))
        if selector is None:
            return DECLINE  # fail-closed
        key = "power_count" if m.group("char").lower() == "power" else "toughness_count"
        return [EffectSpec("pt_cda", {"affects": "self", key: selector})]
    return None


# "This spell can't be countered." (RULE 118-area) — printed on a
# permanent as a standing line even though it only matters while the
# object is still a spell on the stack; `catalogue.handlers` claims the
# identical phrase for the instant/sorcery spell_effect path, see
# `CANT_BE_COUNTERED_RE`'s docstring for why both need it.
def static_cant_be_countered_self(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    if CANT_BE_COUNTERED_RE.fullmatch(text):
        return [EffectSpec("cant_be_countered", {})]
    return None


# "Spells you control can't be countered." / "Creature spells you
# control can't be countered." (Hexing Squelcher/Rionya-shaped) — a
# standing grant, not the spell's own bare flag `CANT_BE_COUNTERED_RE`
# claims above.
def static_grant_cant_be_countered(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = GRANT_CANT_BE_COUNTERED_RE.fullmatch(text)
    if m is not None:
        if m.group("subtype"):
            # RULE 205.3: "Human spells you control can't be countered." (Goldbug, Scrappy Scout) -- a subtype word
            # only; any other adjective (a colour, a card type) keeps its own scope or stays unclaimed.
            word = m.group("subtype").lower()
            if word not in SUBTYPES:
                return None
            return [EffectSpec("grant_cant_be_countered", {"scope": "subtype_spells_you_control", "subtype": word})]
        scope = "creature_spells_you_control" if m.group("creature") else "you"
        return [EffectSpec("grant_cant_be_countered", {"scope": scope})]
    return None


# RULE 701.19a: "Your opponents can't search libraries." (Stranglehold)
def static_grant_search_prohibited(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    if GRANT_SEARCH_PROHIBITED_RE.fullmatch(text):
        return [EffectSpec("grant_search_prohibited", {})]
    return None


# RULE 500.7/700.4: "If an opponent would begin an extra turn, that
# player skips that turn instead." (Stranglehold's own second clause)
def static_grant_skip_extra_turns(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    if GRANT_SKIP_EXTRA_TURNS_RE.fullmatch(text):
        return [EffectSpec("grant_skip_extra_turns", {})]
    return None


def static_lands_every_basic_type(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    if LANDS_EVERY_BASIC_TYPE_RE.fullmatch(text):
        return [EffectSpec("type_change", {
            "affects": scoped_group_selector("you", {"card_type": "land"}), "add_subtypes": list(BASIC_LAND_TYPE_LIST),
        })]
    return None


def static_flash_permission(ctx: StaticContext) -> StaticResult:
    m = FLASH_PERMISSION_RE.fullmatch(ctx.text)
    if m is None:
        return None
    params = flash_permission_filter(m.group("filter"))
    if params is None:
        return None
    # "Any player may cast sliver spells as though they had flash." (Quick Sliver): not scoped to the controller.
    if m.group("who").lower() == "any player":
        params["any_player"] = True
    return [EffectSpec("flash_permission", params)]


#: "Creature cards you own that aren't on the battlefield have flash." (Teferi, Mage of Zhalfir / Druid of Argoth) --
#: the cast-timing permission only (see the ticket decision: "has flash" is not a granted keyword here), scoped to cards
#: the controller owns.
_OWNED_CREATURE_CARDS_FLASH_RE = re.compile(
    r"^creature cards you own that aren'?t on the battlefield have flash$", re.IGNORECASE)
#: "Familiar spells you cast have flash." (Chea, Friend to Maybe Too Many) -- the same timing permission over a spell
#: phrase, the "you cast" wording being the controller scope the permission already has.
_SPELLS_YOU_CAST_HAVE_FLASH_RE = re.compile(
    r"^(?P<filter>.+?) spells you cast have flash$", re.IGNORECASE)
#: "Each opponent can cast spells only any time they could cast a sorcery." (RULE 601.3b timing restriction).
#: "You may cast the first creature spell you cast each turn as though it had flash." (The Blue Spirit) -- the
#: creature-spell flash permission, live only until the controller has cast a creature spell this turn.
_FIRST_CREATURE_SPELL_FLASH_RE = re.compile(
    r"^you may cast the first creature spell you cast each turn as though it had flash$", re.IGNORECASE)
_OPPONENTS_SORCERY_SPEED_RE = re.compile(
    r"^each opponent can cast spells only any time they could cast a sorcery$", re.IGNORECASE)


def static_cast_timing_flash_and_restriction(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    if _OWNED_CREATURE_CARDS_FLASH_RE.fullmatch(text):
        return [EffectSpec("flash_permission", {"creature_only": True, "owned_cards": True})]
    m = _SPELLS_YOU_CAST_HAVE_FLASH_RE.fullmatch(text)
    if m is not None:
        params = flash_permission_filter(m.group("filter"))
        return [EffectSpec("flash_permission", params)] if params else None
    if _OPPONENTS_SORCERY_SPEED_RE.fullmatch(text):
        return [EffectSpec("sorcery_speed_only", {})]
    if _FIRST_CREATURE_SPELL_FLASH_RE.fullmatch(text):
        return [EffectSpec("flash_permission", {
            "creature_only": True, "active_if": {"kind": "first_creature_spell_this_turn"}})]
    return None
