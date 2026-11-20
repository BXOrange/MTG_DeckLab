"""Segmenter: line rows costs (split from `segmenter.py` by PAR-172's method, ENG-59)."""

from __future__ import annotations

import re
from typing import Optional
from ..catalogue.count_phrase import NUMBER_WORD_PATTERN, number_value
from ..catalogue.static_handlers import static_condition
from ..catalogue.subgrammars import resolve_color_word
from ..spec import AbilitySpec, EffectSpec
from .segment_types import Segment
from .line_types import LineContext
from .cost_line_patterns import (
    ADDITIONAL_COST_LINE_RE,
    ADDITIONAL_COST_OPTIONAL_PREFIX_RE,
    ALT_COST_DISCARD_LAND_TYPE_RE,
    ALT_COST_EXILE_HAND_COLOR_COUNT_RE,
    ALT_COST_EXILE_HAND_COLOR_IF_NOT_YOUR_TURN_RE,
    ALT_COST_EXILE_HAND_COLOR_RE,
    ALT_COST_PAY_LIFE_AND_EXILE_HAND_COLOR_RE,
    ALT_COST_PAY_LIFE_IF_CONTROL_LAND_RE,
    ALT_COST_PAY_MANA_AND_RETURN_BASIC_LAND_RE,
    ALT_COST_PAY_MANA_IF_ATTACKING_RE,
    ALT_COST_PAY_MANA_IF_CONDITION_RE,
    ALT_COST_PAY_MANA_TRAILING_IF_RE,
    ALT_COST_SACRIFICE_IF_YOUR_TURN_RE,
    ALT_COST_PAY_MANA_IF_TREASURE_RE,
    ALT_COST_PAY_MANA_IF_YOU_ATTACKED_RE,
    ALT_COST_PAY_MANA_RE,
    ALT_COST_RETURN_ONE_RE,
    ALT_COST_RETURN_TWO_RE,
    ALT_COST_SACRIFICE_COUNT_RE,
    ALT_COST_SACRIFICE_IF_CONTROL_LAND_RE,
    ALT_COST_SACRIFICE_NONTOKEN_COLOR_CREATURE_RE,
    ALT_COST_SACRIFICE_TYPE_RE,
    ALT_COST_TAP_CREATURE_IF_CONTROL_LAND_RE,
    BEFORE_BLOCKERS_CAST_ONLY_RE,
    CAST_MANA_SOURCE_RESTRICTION_RE,
    CAST_ONLY_IF_ANOTHER_COLOR_RE,
    COLLECT_EVIDENCE_COST_REDUCTION_RE,
    COMBAT_CAST_ONLY_RE,
    CONDITIONAL_FLASH_FOR_EXTRA_MANA_RE,
    CONDITIONAL_FLASH_IF_BEHOLD_RE,
    CONDITIONAL_FLASH_IF_TARGETS_COMMANDER_RE,
    CONDITIONAL_FLASH_IF_TARGETS_OWN_PERMANENT_RE,
    CONDITIONAL_FLASH_STATE_RES,
    DECLARE_ATTACKERS_IF_ATTACKED_RE,
    FLASH_THEN_CLEANUP_SAC_RE,
    FREE_CAST_IF_ANOTHER_COLOR_RE,
    FREE_CAST_IF_COMMANDER_RE,
    FREE_CAST_IF_OPPONENT_FOREST_YOU_ISLAND_RE,
    FREE_CAST_IF_OPPONENT_SPELLS_RE,
    STRIVE_LINE_RE,
    additional_cost_dict,
)

# RULE 118.9 alternative costs — checked regardless of card type
# (unlike every other row `allow_spell_effect` gates below): a spell's
# mana cost doesn't care what it becomes once it resolves, so the
# Bringer cycle prints "You may pay <mana> rather than pay this
# spell's mana cost." on an ordinary creature spell exactly the same
# way Force of Will prints it on an instant. Widening `_is_spell`
# itself to include creatures was tried and reverted — it also gates
# unrelated bare-imperative rows below (Strive, free-cast conditions, …)
# that broke real creature static/replacement-clause tests when creature
# cards started reaching them, so only this alt_cost family is pulled
# out and made unconditional instead.
def line_alt_cost_exile_hand_color(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    pitch = ALT_COST_EXILE_HAND_COLOR_RE.match(raw)
    if pitch is not None:
        color = resolve_color_word(pitch.group("color"))
        if color is None:
            return Segment(raw=raw)  # unrecognised colour word → unclaimed
        spec = AbilitySpec(
            "spell_effect",
            effects=[],
            alt_cost={"exile_hand_card_color": color},
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def line_alt_cost_sacrifice_filter(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    sac_filter = ALT_COST_SACRIFICE_NONTOKEN_COLOR_CREATURE_RE.match(raw)
    if sac_filter is not None:
        color = resolve_color_word(sac_filter.group("color"))
        if color is None:
            return Segment(raw=raw)  # unrecognised colour word → unclaimed
        spec = AbilitySpec(
            "spell_effect",
            effects=[],
            alt_cost={"sacrifice_filter": {"card_type": "creature", "color": color, "nontoken": True}},
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def line_alt_cost_sacrifice_type(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    sac_type = ALT_COST_SACRIFICE_TYPE_RE.match(raw)
    if sac_type is not None:
        spec = AbilitySpec(
            "spell_effect",
            effects=[],
            alt_cost={"sacrifice": sac_type.group("what").lower()},
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def line_alt_cost_return_two(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    ret_two = ALT_COST_RETURN_TWO_RE.match(raw)
    if ret_two is not None:
        spec = AbilitySpec(
            "spell_effect",
            effects=[],
            alt_cost={"return_to_hand_count": [int(ret_two.group("count")), ret_two.group("subtype").lower()]},
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    ret_one = ALT_COST_RETURN_ONE_RE.match(raw)
    if ret_one is not None:
        spec = AbilitySpec(
            "spell_effect",
            effects=[],
            alt_cost={"return_to_hand": ret_one.group("subtype").lower()},
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def line_alt_cost_pay_life_if_control_land(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    pay_if = ALT_COST_PAY_LIFE_IF_CONTROL_LAND_RE.match(raw)
    if pay_if is not None:
        spec = AbilitySpec(
            "spell_effect",
            effects=[],
            alt_cost={
                "pay_life": int(pay_if.group("n")),
                "condition": {"control_land_type": pay_if.group("land").lower()},
            },
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def line_alt_cost_pay_mana_if_attacking(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    pay_mana_if_attacking = ALT_COST_PAY_MANA_IF_ATTACKING_RE.match(raw)
    if pay_mana_if_attacking is not None:
        spec = AbilitySpec(
            "spell_effect",
            effects=[],
            alt_cost={
                "mana": re.sub(r"\s+", "", pay_mana_if_attacking.group("mana")),
                "condition": {
                    "creatures_attacking_at_least": int(pay_mana_if_attacking.group("n")),
                },
            },
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def line_alt_cost_pay_mana_if_condition(ctx: LineContext) -> Optional[Segment]:
    """PAR-283: "If <shared-vocabulary condition>, you may pay <cost> rather than pay this spell's mana cost." (the Trap
    cycle). The condition is whatever `static_condition` reads; an unreadable one leaves the line unclaimed."""
    raw = ctx.raw
    m = ALT_COST_PAY_MANA_IF_CONDITION_RE.match(raw) or ALT_COST_PAY_MANA_TRAILING_IF_RE.match(raw)
    if m is None:
        return None
    # Spelled-out counts fold to digits so one numeric grammar reads both spellings ("thirteen or more creatures").
    cond_text = re.sub(
        rf"\b(?!\d){NUMBER_WORD_PATTERN}\b", lambda w: str(number_value(w.group(0).lower())), m.group("cond"),
        flags=re.I,
    )
    condition = static_condition(cond_text)
    if condition is None:
        return None
    spec = AbilitySpec(
        "spell_effect",
        effects=[],
        alt_cost={"mana": re.sub(r"\s+", "", m.group("mana")), "condition": condition},
        raw_text=raw,
        parser=ctx.provenance,
    )
    return Segment(raw=raw, spec=spec, claimed=True)


def line_alt_cost_sacrifice_if_your_turn(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    m = ALT_COST_SACRIFICE_IF_YOUR_TURN_RE.match(raw)
    if m is None:
        return None
    spec = AbilitySpec(
        "spell_effect", effects=[],
        alt_cost={"sacrifice": m.group("what").lower(), "condition": {"your_turn": True}},
        raw_text=raw, parser=ctx.provenance,
    )
    return Segment(raw=raw, spec=spec, claimed=True)


def line_alt_cost_pay_mana_if_you_attacked(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    pay_mana_if_you_attacked = ALT_COST_PAY_MANA_IF_YOU_ATTACKED_RE.match(raw)
    if pay_mana_if_you_attacked is not None:
        spec = AbilitySpec(
            "spell_effect",
            effects=[],
            alt_cost={
                "mana": re.sub(r"\s+", "", pay_mana_if_you_attacked.group("mana")),
                "condition": {"you_attacked_this_turn": True},
            },
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def line_alt_cost_pay_mana(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    pay_mana = ALT_COST_PAY_MANA_RE.match(raw)
    if pay_mana is not None:
        spec = AbilitySpec(
            "spell_effect",
            effects=[],
            alt_cost={"mana": re.sub(r"\s+", "", pay_mana.group("mana"))},
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def line_alt_cost_sacrifice_if_control_land(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    sac_if = ALT_COST_SACRIFICE_IF_CONTROL_LAND_RE.match(raw)
    if sac_if is not None:
        spec = AbilitySpec(
            "spell_effect",
            effects=[],
            alt_cost={
                "sacrifice": sac_if.group("what").lower(),
                "condition": {"control_land_type": sac_if.group("land").lower()},
            },
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def line_alt_cost_tap_creature_if_control_land(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    tap_if = ALT_COST_TAP_CREATURE_IF_CONTROL_LAND_RE.match(raw)
    if tap_if is not None:
        spec = AbilitySpec(
            "spell_effect",
            effects=[],
            alt_cost={
                "tap_others": [1, "creature"],
                "condition": {"control_land_type": tap_if.group("land").lower()},
            },
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def line_alt_cost_pay_mana_and_return_land(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    pay_and_return = ALT_COST_PAY_MANA_AND_RETURN_BASIC_LAND_RE.match(raw)
    if pay_and_return is not None:
        spec = AbilitySpec(
            "spell_effect",
            effects=[],
            alt_cost={
                "mana": re.sub(r"\s+", "", pay_and_return.group("mana")),
                "return_to_hand_count": [1, "basic land"],
            },
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def line_alt_cost_sacrifice_count(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    sac_count = ALT_COST_SACRIFICE_COUNT_RE.match(raw)
    if sac_count is not None:
        word = sac_count.group("subtype").lower()
        if sac_count.group("color"):
            # The cost's permanent phrase for "black creatures": `<colour>_<type>` (`continuous.matches_permanent_word`).
            word = f"{sac_count.group('color').strip().lower()}_{word}"
        alt_cost = {"sacrifice_count": [int(sac_count.group("n")), word]}
        if sac_count.group("life"):
            alt_cost["pay_life"] = int(sac_count.group("life"))
        spec = AbilitySpec(
            "spell_effect",
            effects=[],
            alt_cost=alt_cost,
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def line_alt_cost_exile_hand_color_count(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    pitch_color_count = ALT_COST_EXILE_HAND_COLOR_COUNT_RE.match(raw)
    if pitch_color_count is not None:
        color = resolve_color_word(pitch_color_count.group("color"))
        if color is None:
            return Segment(raw=raw)
        spec = AbilitySpec(
            "spell_effect",
            effects=[],
            alt_cost={"exile_hand_card_color_count": [2, color]},
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def line_alt_cost_exile_hand_if_not_your_turn(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    pitch_if_not_your_turn = ALT_COST_EXILE_HAND_COLOR_IF_NOT_YOUR_TURN_RE.match(raw)
    if pitch_if_not_your_turn is not None:
        color = resolve_color_word(pitch_if_not_your_turn.group("color"))
        if color is None:
            return Segment(raw=raw)
        spec = AbilitySpec(
            "spell_effect",
            effects=[],
            alt_cost={
                "exile_hand_card_color": color,
                "condition": {"not_your_turn": True},
            },
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def line_alt_cost_pay_life_and_exile_hand(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    pitch_pay_life = ALT_COST_PAY_LIFE_AND_EXILE_HAND_COLOR_RE.match(raw)
    if pitch_pay_life is not None:
        color = resolve_color_word(pitch_pay_life.group("color"))
        if color is None:
            return Segment(raw=raw)
        spec = AbilitySpec(
            "spell_effect",
            effects=[],
            alt_cost={
                "pay_life": int(pitch_pay_life.group("n")),
                "exile_hand_card_color": color,
            },
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def line_alt_cost_discard_land(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    discard_land = ALT_COST_DISCARD_LAND_TYPE_RE.match(raw)
    if discard_land is not None:
        spec = AbilitySpec(
            "spell_effect",
            effects=[],
            alt_cost={"discard_land_type": discard_land.group("land").lower()},
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def line_alt_cost_pay_mana_if_treasure(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    pay_mana_if_treasure = ALT_COST_PAY_MANA_IF_TREASURE_RE.match(raw)
    if pay_mana_if_treasure is not None:
        spec = AbilitySpec(
            "spell_effect",
            effects=[],
            alt_cost={
                "mana": re.sub(r"\s+", "", pay_mana_if_treasure.group("mana")),
                "mana_source_kind": "treasure",
            },
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def line_cast_mana_source_restriction(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    cast_mana_source = CAST_MANA_SOURCE_RESTRICTION_RE.match(raw)
    if cast_mana_source is not None:
        kind = {"basic lands": "basic_land", "creatures": "creature"}[
            cast_mana_source.group("kind").lower()
        ]
        spec = AbilitySpec(
            "spell_effect",
            effects=[],
            cast_mana_source_restriction=kind,
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


# RULE 601.2b/604.3 additional cost — checked before every other wrapper
# since it has neither a trigger word nor a colon (so it can't be
# mistaken for one of those shapes below). Not gated by
# ``allow_spell_effect``: the "as an additional cost to cast this spell,"
# wrapper is unambiguous and applies to a creature/other permanent spell
# just as much as an instant/sorcery (Kinsbaile Aspirant/Lys Alana
# Dignitary/Silvergill Mentor — Behold, PAR-29), and the spec it emits
# carries no bare imperative for the gate to guard against.
def line_collect_evidence_discount(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    evidence_discount = COLLECT_EVIDENCE_COST_REDUCTION_RE.match(raw)
    if evidence_discount is not None:
        cost = {"collect_evidence": int(evidence_discount.group("evidence"))}
        cost_spec = AbilitySpec(
            "spell_effect", effects=[], additional_cost=cost,
            additional_cost_optional=True, raw_text=raw, parser=provenance,
        )
        reduction_spec = AbilitySpec(
            "static",
            effects=[EffectSpec("cost_reduction", {
                "affects": "self", "generic": int(evidence_discount.group("reduction")),
                "active_if": {"kind": "flag", "flag": "additional_cost_paid"},
            })],
            raw_text=raw, parser=provenance,
        )
        return Segment(raw=raw, spec=cost_spec, extra_specs=[reduction_spec], claimed=True)
    return None


def line_additional_cost_line(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    add_cost = ADDITIONAL_COST_LINE_RE.match(raw)
    if add_cost is not None:
        cost_text = add_cost.group("cost")
        # PAR-30 / RULE 601.2b: "you may <cost>" → an *optional* additional
        # cost, offered as its own cast variant and recorded on
        # `GameObject.additional_cost_paid`.
        optional_m = ADDITIONAL_COST_OPTIONAL_PREFIX_RE.match(cost_text.strip())
        is_optional = optional_m is not None
        if is_optional:
            cost_text = optional_m.group("cost")
        cost = additional_cost_dict(cost_text)
        if cost is None:
            return Segment(raw=raw)  # unrecognised cost shape → unclaimed
        spec = AbilitySpec(
            "spell_effect",
            effects=[],
            additional_cost=cost,
            additional_cost_optional=is_optional or "sacrifice_or_mana" in cost or "or_mana" in cost,  # "either": both branches mandatory
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


# PAR-35's casting clauses are unambiguous spell metadata, so like an
# additional cost they apply to permanent spells too (Harbinger of the
# Tides / Armor of Thorns), not only bare instant/sorcery effects.
def line_declare_attackers_if_attacked(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    if DECLARE_ATTACKERS_IF_ATTACKED_RE.match(raw):
        return Segment(raw=raw, spec=AbilitySpec(
            "spell_effect", effects=[],
            cast_timing_restriction={"step": "declare_attackers", "controller_attacked": True},
            raw_text=raw, parser=provenance,
        ), claimed=True)
    return None


def line_combat_cast_only(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    combat_cast = COMBAT_CAST_ONLY_RE.fullmatch(raw)
    if combat_cast:
        groups = combat_cast.groupdict()
        restriction = {"phase": "combat"} if groups["window"].lower() == "during combat" else {"step": "declare_blockers"}
        if groups["turn"]:
            restriction["your_turn" if groups["turn"].lower() == "your" else "opponents_turn"] = True
        if groups["point"]:
            if "step" in restriction:
                return Segment(raw=raw)  # contradictory or unsupported composite
            restriction[groups["point"].lower() + "_blockers"] = True
        return Segment(raw=raw, spec=AbilitySpec(
            "spell_effect", effects=[], cast_timing_restriction=restriction,
            raw_text=raw, parser=provenance,
        ), claimed=True)
    return None


def line_before_blockers_cast_only(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    if BEFORE_BLOCKERS_CAST_ONLY_RE.fullmatch(raw):
        return Segment(raw=raw, spec=AbilitySpec(
            "spell_effect", effects=[],
            cast_timing_restriction={"before_blockers": True, "first_combat": True},
            raw_text=raw, parser=provenance,
        ), claimed=True)
    return None


def line_cast_only_if_another_color(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    another_cast = CAST_ONLY_IF_ANOTHER_COLOR_RE.match(raw)
    if another_cast is not None:
        color = {"white": "W", "blue": "U", "black": "B", "red": "R", "green": "G"}[
            another_cast.group("color").lower()
        ]
        return Segment(raw=raw, spec=AbilitySpec(
            "spell_effect", effects=[],
            cast_condition={"another_spell_cast_this_turn": {"color": color}},
            raw_text=raw, parser=provenance,
        ), claimed=True)
    return None


def line_conditional_flash_for_mana(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    flash_for_mana = CONDITIONAL_FLASH_FOR_EXTRA_MANA_RE.match(raw)
    if flash_for_mana is not None:
        return Segment(raw=raw, spec=AbilitySpec(
            "spell_effect", effects=[], conditional_flash={"unconditional": True},
            flash_extra_cost=re.sub(r"\s+", "", flash_for_mana.group("cost")),
            raw_text=raw, parser=provenance,
        ), claimed=True)
    return None


def line_conditional_flash_board_state(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    if CONDITIONAL_FLASH_IF_TARGETS_OWN_PERMANENT_RE.match(raw):
        spec = AbilitySpec(
            "spell_effect", effects=[], conditional_flash={"targets_a_permanent_you_control": True},
            raw_text=raw, parser=ctx.provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    for state_flash_re in CONDITIONAL_FLASH_STATE_RES:
        state_flash = state_flash_re.match(raw)
        if state_flash is None:
            continue
        flash_gate = static_condition(state_flash.group("cond"))
        if flash_gate is not None:
            spec = AbilitySpec(
                "spell_effect", effects=[], conditional_flash={"active_if": flash_gate},
                raw_text=raw, parser=ctx.provenance,
            )
            return Segment(raw=raw, spec=spec, claimed=True)
    return None


def line_flash_then_cleanup_sac(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    if FLASH_THEN_CLEANUP_SAC_RE.match(raw):
        return Segment(raw=raw, spec=AbilitySpec(
            "triggered",
            [EffectSpec("create_delayed_trigger", {
                "step": "cleanup", "scope": "controller",
                "effects": [{"type": "sacrifice_self", "params": {}}],
                "description": "Instant-speed cast: sacrifice at next cleanup",
            }, condition={"cast_outside_sorcery_speed": True})],
            trigger={"event": "ENTERS_BATTLEFIELD", "condition": {"subject": "self"}},
            conditional_flash={"unconditional": True}, raw_text=raw, parser=provenance,
        ), claimed=True)
    return None


def line_spell_free_cast_conditions(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    allow_spell_effect = ctx.allow_spell_effect
    provenance = ctx.provenance
    if allow_spell_effect:
        # RULE 601.2f-adjacent condition-gated free-cast alternative cost —
        # "If you control a commander, you may cast this spell without
        # paying its mana cost." — its own standalone line, same treatment.
        if FREE_CAST_IF_COMMANDER_RE.match(raw):
            spec = AbilitySpec(
                "spell_effect",
                effects=[],
                free_cast_condition={"control_commander": True},
                raw_text=raw,
                parser=provenance,
            )
            return Segment(raw=raw, spec=spec, claimed=True)
        another_color = FREE_CAST_IF_ANOTHER_COLOR_RE.match(raw)
        if another_color is not None:
            color = {"white": "W", "blue": "U", "black": "B", "red": "R", "green": "G"}[
                another_color.group("color").lower()
            ]
            return Segment(raw=raw, spec=AbilitySpec(
                "spell_effect", effects=[],
                free_cast_condition={"another_spell_cast_this_turn": {"color": color}},
                raw_text=raw, parser=provenance,
            ), claimed=True)

        opp_spells = FREE_CAST_IF_OPPONENT_SPELLS_RE.match(raw)
        if opp_spells is not None:
            spec = AbilitySpec(
                "spell_effect",
                effects=[],
                free_cast_condition={
                    "opponent_spells_cast_this_turn_at_least": int(opp_spells.group("n"))
                },
                raw_text=raw,
                parser=provenance,
            )
            return Segment(raw=raw, spec=spec, claimed=True)

        if FREE_CAST_IF_OPPONENT_FOREST_YOU_ISLAND_RE.match(raw):
            spec = AbilitySpec(
                "spell_effect",
                effects=[],
                free_cast_condition={"opponent_controls_forest_and_you_control_island": True},
                raw_text=raw,
                parser=provenance,
            )
            return Segment(raw=raw, spec=spec, claimed=True)

        # RULE 702.8b: "You may cast this spell as though it had flash if it
        # targets a commander." (Timely Ward-shaped, MEC-7) — same standalone-
        # line treatment as the free-cast condition just above.
        if CONDITIONAL_FLASH_IF_TARGETS_COMMANDER_RE.match(raw):
            spec = AbilitySpec(
                "spell_effect",
                effects=[],
                conditional_flash={"targets_a_commander": True},
                raw_text=raw,
                parser=provenance,
            )
            return Segment(raw=raw, spec=spec, claimed=True)

        behold_flash = CONDITIONAL_FLASH_IF_BEHOLD_RE.match(raw)
        if behold_flash is not None:
            spec = AbilitySpec(
                "spell_effect",
                effects=[],
                conditional_flash={
                    "controller_beholds_subtype": behold_flash.group("q").strip().lower()
                },
                raw_text=raw,
                parser=provenance,
            )
            return Segment(raw=raw, spec=spec, claimed=True)

        # "Strive — This spell costs <cost> more to cast for each target
        # beyond the first." (MEC-4) — same standalone-line treatment; the
        # cost run is whitespace-collapsed the way `additional_cost_dict`'s
        # neighbours already do, so ``{2} {u}`` and ``{2}{u}`` both parse.
        strive = STRIVE_LINE_RE.match(raw)
        if strive is not None:
            spec = AbilitySpec(
                "spell_effect",
                effects=[],
                strive_cost=re.sub(r"\s+", "", strive.group("cost")),
                raw_text=raw,
                parser=provenance,
            )
            return Segment(raw=raw, spec=spec, claimed=True)
    return None
