"""Static-ability helpers: rows cost tax (split from `static_handlers` by PAR-172's method, ENG-59)."""

from __future__ import annotations

import re
from typing import Any, Optional
from ..named_card_statics import named_card_static_specs
from ...spec import EffectSpec
from ..subgrammars import count_of
from ..count_phrase import parse_amount_phrase, parse_count_phrase
from ..subtype_vocabulary import SUBTYPES
from .anthem_patterns import CARD_TYPE_WORDS, COLOR_WORDS
from .object_scope import group_selector, scoped_group_selector, singularize
from .cost_patterns import (
    ACTIVATION_COST_REDUCTION_TYPE_RE,
    ACTIVATION_PROHIBITION_OPPONENTS_RE,
    ACTIVATION_PROHIBITION_RE,
    CANT_CAST_OPPONENTS_HAND_ONLY_RE,
    CANT_CAST_DEFENDING_PLAYER_RE,
    CANT_CAST_OPPONENTS_YOUR_TURN_RE,
    CANT_CAST_OR_ACTIVATE_OPPONENTS_RE,
    CAST_LIMIT_NONCREATURE_RE,
    CAST_LIMIT_RE,
    EQUIP_ACTIVATION_DISCOUNT_RE,
    EQUIP_SELF_DISCOUNT_RE,
    EXTRA_LAND_DROP_RE,
    SECOND_SPELL_COST_REDUCTION_RE,
    SELF_COST_REDUCTION_COLORED_RE,
    SELF_COST_REDUCTION_FOR_EACH_RE,
    SELF_COST_REDUCTION_IF_RE,
    SELF_COST_REDUCTION_WHERE_X_RE,
    SPELL_COST_SUBTYPE_UNION_RE,
    SPELL_COST_SUBTYPE_WORDS,
    SPELL_COST_TAX_COLOR_RE,
    SPELL_COST_TAX_COMMANDER_RE,
    SPELL_COST_TAX_OPPONENTS_RE,
    SPELL_COST_TAX_RE,
    SPELL_COST_TAX_THAT_TARGET_RE,
    SPELL_COST_TAX_YOU_CAST_RE,
    SPELL_TYPE_WORDS,
    SPELL_UNION_SPLIT_RE,
    self_cost_per,
    targets_reduction_criteria,
    tax_target_alternatives,
    type_word_list,
)
from .static_conditions import static_condition
from .matcher_types import DECLINE, StaticContext, StaticResult

def static_activation_prohibition_opponents(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = ACTIVATION_PROHIBITION_OPPONENTS_RE.fullmatch(text)
    if m is not None:
        card_type = singularize(m.group("word"))
        if card_type not in CARD_TYPE_WORDS:
            return DECLINE  # fail-closed — an unrecognised type-scope
        return [
            EffectSpec(
                "activation_prohibition",
                {"affects": scoped_group_selector("opponents", {"card_type": card_type})},
            )
        ]
    return None


def static_cant_cast_opponents_your_turn(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    if CANT_CAST_OPPONENTS_YOUR_TURN_RE.fullmatch(text):
        return [EffectSpec("cast_prohibition", {"scope": "opponents", "active_if": {"kind": "your_turn"}})]
    return None


def static_cant_cast_defending_player(ctx: StaticContext) -> StaticResult:
    if CANT_CAST_DEFENDING_PLAYER_RE.fullmatch(ctx.text):
        return [EffectSpec("cast_prohibition", {"scope": "all", "defending_player_of_source": True})]
    return None


def static_cant_cast_opponents_hand_only(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    if CANT_CAST_OPPONENTS_HAND_ONLY_RE.fullmatch(text):
        return [EffectSpec("cast_prohibition", {"scope": "opponents", "hand_only": True})]
    return None


def static_cant_cast_or_activate_opponents(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = CANT_CAST_OR_ACTIVATE_OPPONENTS_RE.fullmatch(text)
    if m is not None:
        card_types = type_word_list(m.group("types"))
        if card_types is None:
            return DECLINE  # fail-closed — an unrecognised type in the list
        return [
            EffectSpec("cast_prohibition", {"scope": "opponents"}),
            EffectSpec(
                "activation_prohibition",
                {"affects": scoped_group_selector("opponents", {"card_type_any": card_types})},
            ),
        ]
    return None


def static_named_card(ctx: StaticContext) -> StaticResult:
    return named_card_static_specs(ctx.text)


def static_activation_prohibition(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = ACTIVATION_PROHIBITION_RE.fullmatch(text)
    if m is not None:
        card_type = singularize(m.group("word"))
        if card_type not in CARD_TYPE_WORDS:
            return DECLINE  # fail-closed — an unrecognised type-scope
        return [EffectSpec("activation_prohibition", {"affects": group_selector(False, {"card_type": card_type})})]
    return None


def static_spell_cost_tax(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = SPELL_COST_TAX_RE.fullmatch(text)
    if m is not None:
        word = (m.group("word") or "").lower()
        # A bare "spells cost {N} more/less to cast" (no type word — Sphere of
        # Resistance) taxes *every* spell: a falsy ``spell_type`` means "no
        # type filter" in `continuous.cost_reduction_for`. A typed variant
        # must name a recognised card type (fail-closed).
        if word and word not in SPELL_TYPE_WORDS:
            return DECLINE
        params: dict = {
            "affects": "all_spells",
            "generic": int(m.group("n")),
            "increase": m.group("dir") == "more",
        }
        if word:
            params["spell_type"] = word
        return [EffectSpec("cost_reduction", params)]
    return None


def _spell_mana_value_bound(m: "re.Match[str]") -> dict:
    """RULE 202.3: "with mana value N or greater/less" on a cost-modified spell -> the spell's own mana-value bound."""
    if m.group("mv") is None:
        return {}
    return {"spell_min_mana_value" if m.group("mvdir").lower() == "greater" else "spell_max_mana_value": int(m.group("mv"))}


def static_spell_cost_tax_color(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = SPELL_COST_TAX_COLOR_RE.fullmatch(text)
    if m is not None:
        params = {
            "generic": int(m.group("n")),
            "increase": m.group("dir") == "more",
            "spell_color": COLOR_WORDS[m.group("color").lower()],
            **_spell_mana_value_bound(m),
        }
        return [EffectSpec("cost_reduction", params)]
    return None


def static_spell_cost_tax_commander(ctx: StaticContext) -> StaticResult:
    m = SPELL_COST_TAX_COMMANDER_RE.fullmatch(ctx.text)
    if m is None:
        return None
    return [EffectSpec("cost_reduction", {
        "generic": int(m.group("n")), "increase": m.group("dir") == "more", "spell_is_commander": True,
    })]


def static_spell_cost_tax_that_target(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = SPELL_COST_TAX_THAT_TARGET_RE.fullmatch(text)
    if m is not None:
        params = {}
        if m.group("who").lower() != "you":
            params["affects"] = "opponents_spells"
        if m.group("life"):
            params.update({"generic": 0, "life": int(m.group("life")), "increase": True})
        else:
            params.update({"generic": int(m.group("n")), "increase": m.group("dir") == "more"})
        if m.group("target").strip() == "~":
            params["targets_source"] = True
        else:
            alternatives = tax_target_alternatives(m.group("target"))
            if alternatives is None:
                return DECLINE
            params["if_targets"] = alternatives
        return [EffectSpec("cost_reduction", params)]
    return None


def static_spell_cost_tax_opponents(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = SPELL_COST_TAX_OPPONENTS_RE.fullmatch(text)
    if m is not None:
        params = {
            "affects": "opponents_spells",
            "generic": int(m.group("n")),
            "increase": m.group("dir") == "more",
        }
        return [EffectSpec("cost_reduction", params)]
    return None


def _spell_subtype_union(subjects: str) -> Optional[list[str]]:
    """The creature types of a "<A> spells and <B> spells" / "<A> and <B>" subject list, or ``None`` when any member
    is not a known subtype (a main spell type, a colour, "historic"...)."""
    words = [w.removesuffix(" spells") for w in SPELL_UNION_SPLIT_RE.split(subjects.lower())]
    if len(words) < 2 or any(w not in SUBTYPES or w in SPELL_TYPE_WORDS for w in words):
        return None
    return words


def static_spell_cost_tax_you_cast(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    union = SPELL_COST_SUBTYPE_UNION_RE.fullmatch(text)
    if union is not None:
        subtypes = _spell_subtype_union(union.group("subjects"))
        if subtypes is not None:
            return [EffectSpec("cost_reduction", {
                "generic": int(union.group("n")), "increase": union.group("dir") == "more",
                **_spell_mana_value_bound(union), "spell_subtype": subtypes,
            })]
        # Not a tribe list (Baral's "instant and sorcery"): fall through to the main-type pair below.
    m = SPELL_COST_TAX_YOU_CAST_RE.fullmatch(text)
    if m is not None:
        words = [w.lower() for w in (m.group("word1"), m.group("word2")) if w]
        params = {
            "generic": int(m.group("n")),
            "increase": m.group("dir") == "more",
            **_spell_mana_value_bound(m),
        }
        # A single subtype word ("Aura/Dragon/Equipment spells you cast cost
        # {1} less…" — the Banneret/Warchief tribal-discount cycle) routes to
        # ``spell_subtype`` instead; the two-word "and" compound only ever
        # names main types (Baral). Anything else (colour → its own regex
        # below; "historic"/"commander") stays fail-closed.
        if len(words) == 1 and words[0] in SPELL_COST_SUBTYPE_WORDS:
            params["spell_subtype"] = words[0]
            return [EffectSpec("cost_reduction", params)]
        if any(w not in SPELL_TYPE_WORDS for w in words):
            return DECLINE  # fail-closed — colour/subtype-scoped, not a main type
        if len(words) == 1:
            params["spell_type"] = words[0]
        elif len(words) == 2:
            params["spell_type"] = words
        return [EffectSpec("cost_reduction", params)]
    return None


def static_equip_activation_discount(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = EQUIP_ACTIVATION_DISCOUNT_RE.fullmatch(text)
    if m is not None:
        params = {
            "scope": "activation", "attach_kind": "equip", "generic": int(m.group("n")),
        }
        slot = (m.group("slot") or "").strip().lower()
        if slot == "of other equipment":
            params["other_equipment"] = True
        elif slot:
            params["targets_source"] = True
        return [EffectSpec("cost_reduction", params)]
    return None


def static_equip_self_discount(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = EQUIP_SELF_DISCOUNT_RE.fullmatch(text)
    if m is not None:
        params = {
            "scope": "activation", "attach_kind": "equip", "self_only": True,
            "generic": int(m.group("n")),
        }
        if m.group("what").lower().startswith("other"):
            params["per"] = "other_permanents_you_control_of_subtype_equipment"
        else:
            params["per_target_plus_one_counter"] = True
        return [EffectSpec("cost_reduction", params)]
    return None


def static_activation_cost_reduction_type(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = ACTIVATION_COST_REDUCTION_TYPE_RE.fullmatch(text)
    if m is not None:
        card_type = singularize(m.group("word").lower())
        if card_type not in CARD_TYPE_WORDS:
            return DECLINE  # fail-closed — an unrecognised type-scope
        params = {
            "scope": "activation",
            "affects": group_selector(True, {"card_type": card_type}),
            "generic": int(m.group("n")),
        }
        if m.group("floor"):
            params["min_total"] = int(m.group("floor"))
        return [EffectSpec("cost_reduction", params)]
    return None


# PAR-256 (RULE 601.2f / 602.2b): scoped activated-ability cost modifiers. "<keyword> abilities [of <group>] [you activate]
# cost {N} less/more to activate" (Fluctuator, Boom Scholar, Dragonkin Berserker, Eidolon of Obstruction), "activated
# abilities of <group> cost {N|X} less/more to activate" (Heartstone, Agatha of the Vile Cauldron, Embalmer's Tools), with
# an optional "for each <count>" / ", where X is <amount>" magnitude and a "can't reduce the mana in that cost to less
# than N mana" floor (RULE 118.7). The group, kind and activator axes are parsed apart below, so a new printing that
# recombines them needs no new row.
_ABILITY_COST_MODIFIER_RE = re.compile(
    r"(?P<kind>activated|[a-z]+(?:-[a-z]+)?) abilities(?: of (?P<group>.+?))?(?P<you> you activate)?"
    r" cost \{(?P<n>\d+|x)\} (?P<dir>less|more) to activate"
    r"(?: for each (?P<per>.+?))?(?:, where x is (?P<xphrase>.+?))?\.?"
    r"(?:\s*this effect can'?t reduce the mana in that cost to less than \{?(?P<floor>\d+)\}? mana\.?)?",
    re.IGNORECASE,
)
# "<keyword> costs [you pay | your opponents pay] cost {N} less/more." (Catalyst Stone, Memory Crystal, Warbringer,
# Inquisitive Glimmer): the one keyword cost (RULE 702.34 flashback, 702.27 buyback, 702.109 dash, 709.5e unlock).
_KEYWORD_COST_MODIFIER_RE = re.compile(
    r"(?P<kw>flashback|buyback|dash|unlock) costs(?: (?P<payer>you pay|your opponents pay))?"
    r" cost \{(?P<n>\d+)\} (?P<dir>less|more)\.?",
    re.IGNORECASE,
)
#: Ability kinds `continuous.activation_cost_changes` can tell apart, plus ninjutsu, whose cost is a keyword cost the
#: engine pays through its own action (`CombatMixin.ninjutsu`).
_ABILITY_COST_KINDS: frozenset[str] = frozenset({"cycling", "boast", "exhaust", "power-up", "loyalty"})
_KEYWORD_COST_NINJUTSU = "ninjutsu"
_SOURCE_POWER_SELECTOR = "source_power"  # `continuous.count_selector`'s name for the static source's own power
_GROUP_SUFFIXES: tuple[tuple[str, dict[str, Any]], ...] = (
    (" that target ~", {"targets_source": True}),
    (" you control", {"controller": "you"}),
    (" your opponents control", {"controller": "opponents"}),
    (" in your graveyard", {"zone": "graveyard"}),
)
#: A subtype (not a card type) a group noun may name: Equipment is an artifact subtype (RULE 205.3g).
_GROUP_SUBTYPE_NOUNS: frozenset[str] = frozenset({"equipment"})


def _ability_group(text: Optional[str]) -> "Optional[tuple[dict[str, Any], bool]]":
    """The ``of <group>`` phrase of a scoped activation modifier -> ``(source_group, targets_source)``, or ``None``
    when any word is outside the closed vocabulary (fail-closed)."""
    group: dict[str, Any] = {}
    targets_source = False
    text = (text or "").strip().lower()
    if not text:
        return {}, False
    changed = True
    while changed:
        changed = False
        for suffix, params in _GROUP_SUFFIXES:
            if text.endswith(suffix):
                text = text[: -len(suffix)]
                changed = True
                if "targets_source" in params:
                    targets_source = True
                else:
                    group.update(params)
    if text.startswith("other "):
        group["other"] = True
        text = text[len("other "):]
    if group.get("zone") == "graveyard":
        if not text.endswith(" cards"):
            return None
        text = text[: -len(" cards")]  # "creature cards in your graveyard": a card type, one word
    elif text.endswith(" tokens"):
        group["token"] = True
        text = text[: -len(" tokens")]
    elif text.startswith("nontoken "):
        # MEC-138 (RULE 111.1): "nontoken Rebels" -- a printed card or a copy, never a token.
        group["nontoken"] = True
        text = text[len("nontoken "):]
    noun = text if text in _GROUP_SUBTYPE_NOUNS else singularize(text)
    if noun in _GROUP_SUBTYPE_NOUNS or noun in SUBTYPES:
        group["subtype"] = noun
    elif noun in CARD_TYPE_WORDS and " " not in noun:
        if noun != "permanent":
            group["card_type"] = noun
    else:
        return None
    group.setdefault("controller", "any")
    return group, targets_source


def static_ability_cost_modifier(ctx: StaticContext) -> StaticResult:
    m = _ABILITY_COST_MODIFIER_RE.fullmatch(ctx.text)
    if m is None:
        return None
    kind = m.group("kind").lower()
    increase = m.group("dir").lower() == "more"
    floor = m.group("floor")
    if floor is not None and increase:
        return DECLINE  # a floor only bounds a reduction
    activated = kind == "activated"
    if not activated and kind != _KEYWORD_COST_NINJUTSU and kind not in _ABILITY_COST_KINDS:
        return None
    if activated and m.group("you"):
        return None
    parsed_group = _ability_group(m.group("group"))
    if parsed_group is None:
        return DECLINE
    group, targets_source = parsed_group
    params: dict[str, Any] = {}
    if m.group("n").lower() == "x":
        if not m.group("xphrase") or m.group("per"):
            return DECLINE
        xphrase = m.group("xphrase").strip().lower()
        # "where X is ~'s power" (Agatha of the Vile Cauldron): the modifier source's own derived power (RULE 613).
        amount = _SOURCE_POWER_SELECTOR if xphrase == "~'s power" else parse_amount_phrase(xphrase)
        if amount is None:
            return DECLINE
        params.update({"generic": 1, "per": amount})
    else:
        params["generic"] = int(m.group("n"))
        if m.group("xphrase"):
            return DECLINE
        if m.group("per"):
            per = parse_count_phrase(m.group("per"))
            if per is None:
                return DECLINE
            params["per"] = per
    if increase:
        params["increase"] = True
    if kind == _KEYWORD_COST_NINJUTSU:
        if group or not m.group("you") or floor is not None:
            return DECLINE
        params.update({"scope": "keyword_cost", "keyword": kind, "payer": "you"})
        return [EffectSpec("cost_reduction", params)]
    params["scope"] = "activation"
    if not activated:
        params["ability_kind"] = kind
    if m.group("you"):
        params["activator"] = "you"
    if group:
        params["source_group"] = group
    if targets_source:
        params["targets_source"] = True
    if floor is not None:
        params["min_total"] = int(floor)
    return [EffectSpec("cost_reduction", params)]


# MEC-138 (RULE 601.2f / 602.2b): "activated abilities of <group> cost an additional \"sacrifice a <type>\" to activate"
# (Brutal Suppression) and "mana abilities of ~ cost an additional N life to activate" (Thran Portal): a non-mana cost
# added to the matching abilities. The activator pays it, like any other part of the cost.
_ADDITIONAL_ACTIVATION_COST_RE = re.compile(
    r"(?P<kind>activated|mana) abilities of (?P<group>.+?) cost an additional"
    r" (?:\"sacrifice an? (?P<sac>[a-z]+)\"|(?P<life>\d+) life) to activate\.?",
    re.IGNORECASE,
)
_SELF_GROUP = "~"
#: The permanent types an additional "sacrifice a <type>" cost may name (the engine's `_matches_sacrifice_type` words).
_ADDITIONAL_SACRIFICE_TYPES: frozenset[str] = frozenset({"land", "creature", "artifact", "enchantment"})


def static_additional_activation_cost(ctx: StaticContext) -> StaticResult:
    m = _ADDITIONAL_ACTIVATION_COST_RE.fullmatch(ctx.text)
    if m is None:
        return None
    mana_only = m.group("kind").lower() == "mana"
    group_text = m.group("group").strip().lower()
    if group_text == _SELF_GROUP:
        group: dict[str, Any] = {"self_only": True, "controller": "any"}  # "of ~": only the source's own abilities
    elif mana_only:
        return DECLINE
    else:
        parsed = _ability_group(group_text)
        if parsed is None or parsed[1] or not parsed[0]:
            return DECLINE
        group = parsed[0]
    if m.group("sac"):
        sacrifice = m.group("sac").lower()
        if sacrifice not in _ADDITIONAL_SACRIFICE_TYPES:
            return DECLINE
        additional: dict[str, Any] = {"sacrifice": sacrifice}
    else:
        additional = {"pay_life": int(m.group("life"))}
        if additional["pay_life"] <= 0:
            return DECLINE
    params: dict[str, Any] = {"scope": "activation", "additional_cost": additional, "source_group": group}
    if mana_only:
        params["mana_abilities_only"] = True  # RULE 605.1a: a mana ability is an activated ability, so "activated" covers both
    return [EffectSpec("cost_reduction", params)]


def static_keyword_cost_modifier(ctx: StaticContext) -> StaticResult:
    m = _KEYWORD_COST_MODIFIER_RE.fullmatch(ctx.text)
    if m is None:
        return None
    payer = (m.group("payer") or "").lower()
    params: dict[str, Any] = {
        "scope": "keyword_cost", "keyword": m.group("kw").lower(), "generic": int(m.group("n")),
        "payer": {"you pay": "you", "your opponents pay": "opponents"}.get(payer, "any"),
    }
    if m.group("dir").lower() == "more":
        params["increase"] = True
    return [EffectSpec("cost_reduction", params)]


def static_self_cost_reduction_where_x(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = SELF_COST_REDUCTION_WHERE_X_RE.fullmatch(text)
    if m is not None:

        selector = parse_amount_phrase(m.group("phrase"))
        if selector is not None:
            params = {"affects": "self", "generic": 1, "per": selector}
            if m.group("this_way"):
                # "…to cast this way" (the Visions flashback cycle): only when cast from the graveyard.
                params["active_if"] = {"kind": "source_in_graveyard"}
            return [EffectSpec("cost_reduction", params)]
    return None


def static_self_cost_reduction_for_each(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = SELF_COST_REDUCTION_FOR_EACH_RE.fullmatch(text)
    if m is not None:
        selector = self_cost_per(m.group("phrase"))
        if selector is not None:
            return [EffectSpec("cost_reduction", {
                "affects": "self", "generic": int(m.group("n")), "per": selector,
            })]
    return None


def static_second_spell_cost_reduction(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = SECOND_SPELL_COST_REDUCTION_RE.fullmatch(text)
    if m is not None:
        return [EffectSpec("cost_reduction", {
            "affects": "your_spells", "generic": int(m.group("n")),
            "active_if": {"kind": "spells_cast_this_turn", "min": 1, "max": 1},
        })]
    return None


def static_self_cost_reduction_colored(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = SELF_COST_REDUCTION_COLORED_RE.fullmatch(text)
    if m is not None:
        condition = static_condition(m.group("cond"))
        if condition is None:
            return DECLINE
        symbols = re.findall(r"\{([WUBRG])\}", m.group("symbols"), re.I)
        colors = {symbol.upper() for symbol in symbols}
        if len(colors) != 1:
            return DECLINE
        return [EffectSpec("cost_reduction", {
            "affects": "self", "generic": 0,
            "colored": {colors.pop(): len(symbols)}, "active_if": condition,
        })]
    return None


def static_self_cost_reduction_if(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = SELF_COST_REDUCTION_IF_RE.fullmatch(text)
    if m is not None:
        cond_text = m.group("cond")
        target_crit = targets_reduction_criteria(cond_text)
        if target_crit is not None:
            return [
                EffectSpec(
                    "cost_reduction",
                    {"affects": "self", "generic": int(m.group("n")),
                     "reduce_if_targets": target_crit},
                )
            ]
        condition = static_condition(cond_text)
        if condition is None:
            return DECLINE  # fail-closed — an unrecognised condition clause
        return [
            EffectSpec(
                "cost_reduction",
                {"affects": "self", "generic": int(m.group("n")), "active_if": condition},
            )
        ]
    return None


def static_cast_limit_noncreature(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = CAST_LIMIT_NONCREATURE_RE.fullmatch(text)
    if m is not None:
        return [EffectSpec("cast_limit", {"max_per_turn": int(m.group("n")), "noncreature": True})]
    return None


def static_cast_limit(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = CAST_LIMIT_RE.fullmatch(text)
    if m is not None:
        return [EffectSpec("cast_limit", {"max_per_turn": int(m.group("n"))})]
    return None


def static_extra_land_drop(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = EXTRA_LAND_DROP_RE.fullmatch(text)
    if m is not None:
        affects = "each_player" if m.group("subject").lower() == "each player" else "you"
        return [EffectSpec("extra_land_drop", {"affects": affects, "count": count_of(m.group("n"))})]
    return None
