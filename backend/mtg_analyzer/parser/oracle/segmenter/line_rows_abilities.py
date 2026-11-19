"""Segmenter: line rows abilities (split from `segmenter.py` by PAR-172's method, ENG-59)."""

from __future__ import annotations

import copy
import re
from ..catalogue.clause_reading import ClauseReading
from typing import Any, Optional
from ..catalogue.object_trigger_head import EXCESS_DAMAGE_KEY, parse_object_trigger_head
from ..catalogue.cost_text import scan_cost_text
from ..catalogue.count_phrase import parse_amount_phrase
from ..catalogue.clause_primitives import ACTIVATE_ONLY_ONCE_MARKER
from ..catalogue.flicker_sequences import delayed_dying_return_specs
from ..catalogue.effect_rows.shared import DEFENDING_PLAYER_COMBAT_EVENTS
from ..catalogue.effect_rows.end_of_combat import END_COMBAT_STEP, NEEDS_BLOCK_HEAD
from ..catalogue.effect_rows.pump_stats import DELAYED_SAC_EXILE_TAIL_RE
from ..catalogue.referent_condition import parse_referent_condition
from ..catalogue.replacements import replacement_clause_specs, standing_ability_kind
from ..catalogue.saga import CHAPTER_LINE_RE, parse_chapter_token
from ..catalogue.static_handlers import enter_choice_specs, static_condition, static_effect_specs
from ..spec import AbilitySpec, EffectSpec, GROUP_SUBJECT_KEY_SENTINEL
from .segment_types import Segment
from .optional_peel import peel_optional
from .where_x import bind_x, step_player_difference_specs
from .effect_body import parse_effect_body
from .segment_forms import PHASE_INTERVENING_IF_RE
from .line_types import LineContext
from .trigger_heads import (
    ANOTHER_SUBTYPE_ENTERED_IF_RE,
    ATTACHED_MULTI_EVENT_RE,
    ATTACKED_PLAYER_LOWEST_LIFE_IF_RE,
    ATTACKS_DEFENDER_LANDS_RE,
    ATTACKS_DEFENDER_MOST_LIFE_RE,
    ATTACKS_OPPONENT_THAT_PLAYER_LIFE_RE,
    CARDS_LEAVE_YOUR_GRAVEYARD_TRIGGER_RE,
    CARDS_MILLED_TO_YOUR_GRAVEYARD_TRIGGER_RE,
    CARD_LEAVES_GRAVEYARD_TRIGGER_RE,
    CONTROL_NO_SUBTYPE_WORDS,
    CREATURE_CARD_TO_GY_IF_RE,
    CREATURE_EXPLORES_TRIGGER_RE,
    EACH_MAIN_PHASE_STEPS,
    ENTERS_AND_MAIN_PHASE_RE,
    GRAVEYARD_EXIT_TYPES,
    LAST_TIME_COUNTER_REMOVED_COND_RE,
    MANA_ADDING_EFFECTS,
    NONLAND_CARDS_MILLED_TRIGGER_RE,
    NONLAND_MILLED_COUNT,
    ONCE_PER_TURN_CONDITION_SUFFIX_RE,
    ONE_CARD_MILLED_TO_YOUR_GRAVEYARD_TRIGGER_RE,
    PHASE_DAMAGE_TO_THEM_RE,
    PHASE_STEP_WORDS,
    PHASE_TRIGGER_RE,
    SELF_MILLED_TO_GRAVEYARD_TRIGGER_RE,
    SELF_MULTI_EVENT_RE,
    SOURCE_HARNESSED_IF_RE,
    THAT_PLAYER_HAND_IF_RE,
    THAT_PLAYER_STATE_IF_RE,
    TRIGGER_RE,
    YOU_CONTROL_NO_SUBTYPE_IF_RE,
    YOU_DEALT_DAMAGE_IF_RE,
    active_player_phase_body,
    multi_event_name,
    strip_trigger_once_per_turn_marker,
)
from .activation_clauses import (
    ACTIVATED_RE,
    ACTIVATE_ONLY_IF_TRAILING_RE,
    ACTIVATION_COST_REDUCTION_COLORED_RE,
    ACTIVATION_COST_REDUCTION_CONDITIONAL_RE,
    ACTIVATION_COST_REDUCTION_FOR_EACH_RE,
    ACTIVATION_COST_REDUCTION_GRAVEYARD_MV_RE,
    ACTIVATION_COST_REDUCTION_PARTY_RE,
    ACTIVATION_COST_REDUCTION_WHERE_X_RE,
    ALTERNATIVE_COST_RE,
    ANY_PLAYER_MAY_ACTIVATE_RE,
    COLORS_AMONG_PERMANENTS_MANA_RE,
    COST_PAID_SOURCE_HAD_RE,
    COUNTED_CHOSEN_COLOR_MANA_RE,
    DEVOTION_CHOSEN_COLOR_MANA_RE,
    EXCESS_DAMAGE_EQUAL_RE,
    EXCESS_DAMAGE_EVENT_AMOUNT,
    EXCESS_WHERE_X_RE,
    FIXED_MANA_EFFECT_RE,
    LEAVING_COUNTER_COPY_RE,
    LEAVING_COUNTER_CREATE_TRANSFER_RE,
    LEAVING_COUNTER_DELAYED_COPY_RE,
    LEAVING_COUNTER_IF_ELSE_RE,
    LEAVING_COUNTER_INTERVENING_RE,
    LEAVING_COUNTER_RETURN_LOSE_RE,
    LEAVING_COUNTER_THAT_MANY_RE,
    LEAVING_COUNTER_WHERE_X_RE,
    LOYALTY_LINE_RE,
    MANA_ABILITY_SACRIFICE_X_RE,
    MANA_ABILITY_X_SUPPORTED_RE,
    MANA_EFFECT_RE,
    SPEND_ONLY_CHOSEN_COLOR_RE,
    activation_cost_reduction_selector,
    is_activation_cost,
    stamp_recipient_exclusion,
)
from .cost_line_patterns import REFLEXIVE_TAP_PEEL_RE
from .keyword_and_trigger_conditions import (
    compound_trigger_segment,
    inline_pt_modal_bodies,
    trigger_condition,
    trigger_event,
    variant_trigger_event,
)
from .pronoun_stamping import (
    ATTACKING_PLAYER_EVENTS,
    BARE_IT_RE,
    BATCH_COUNT_AMOUNT,
    CARD_INTRODUCER_RE,
    ETB_INTERVENING_IF_RE,
    HEAD_COUNT_AMOUNTS,
    SELF_DIES_TOKEN_COPY_RE,
    SELF_TOKEN_STATUS_GATES,
    THAT_MANY_RE,
    THAT_PLAYER_BODY_RE,
    retarget_that_player_to_attacked,
    bind_attack_count,
    block_related_body,
    etb_intervening_if,
    event_player_body,
    group_it_would_hit_source,
    pronoun_continues_source,
    reads_event_amount,
    retarget_block_relation,
    retarget_damaged_creature_riders,
    retarget_that_player_to_damaged,
    stamp_group_pronoun,
)
from .late import segment_line_unsplit

# Saga chapter ability "i, ii — <effect>" (RULE 715.2d) — checked before
# every other wrapper since it has neither a trigger word nor a colon.
def line_saga_chapter(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    is_saga = ctx.is_saga
    if is_saga:
        chap = CHAPTER_LINE_RE.match(raw)
        if chap is not None:
            chapters = parse_chapter_token(chap.group("chapters"))
            if chapters is None:
                return Segment(raw=raw)  # unrecognised numeral → unclaimed
            body, optional = peel_optional(chap.group("body"))
            effects = parse_effect_body(body)
            if effects is None:
                return Segment(raw=raw)
            spec = AbilitySpec(
                "triggered",
                effects=effects,
                trigger={"event": "SAGA_CHAPTER", "chapter": chapters},
                optional=optional,
                raw_text=raw,
                parser=provenance,
            )
            return Segment(raw=raw, spec=spec, claimed=True)
    return None


# Planeswalker loyalty ability "[±N]: <effect>" (RULE 606.5c) — its cost is
# the bracket, so it's recognised before the generic activated case (whose
# cost sniff wouldn't accept a bare "[+1]").
def line_loyalty_ability(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    loy = LOYALTY_LINE_RE.match(raw)
    if loy is not None:
        if loy.group(2) == "x":
            # RULE 107.3a / 606.6: the shared cost model already supports
            # announced negative X; positive/unsigned X is not represented.
            if loy.group(1) not in ("-", "−"):
                return Segment(raw=raw)
            delta = "-x"
        else:
            magnitude = int(loy.group(2))
            delta = -magnitude if loy.group(1) in ("-", "−") else magnitude
        body, optional = peel_optional(loy.group("effect").strip())
        effects = parse_effect_body(body)
        if effects is None:
            return Segment(raw=raw)  # unrecognised loyalty effect → unclaimed
        spec = AbilitySpec(
            "activated",
            effects=effects,
            cost={"loyalty": delta},
            optional=optional,
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


# Activated ability "<cost>: <effect>" — checked before the trigger/spell
# cases since a colon unambiguously marks it (RULE 602.1). A trigger has no
# colon, so this never steals one.
def line_activated_ability(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    allow_spell_effect = ctx.allow_spell_effect
    provenance = ctx.provenance
    is_saga = ctx.is_saga
    act = ACTIVATED_RE.match(raw)
    if act is not None and is_activation_cost(act.group("cost")):
        alternative = ALTERNATIVE_COST_RE.fullmatch(act.group("cost").strip())
        if alternative is not None:
            # ENG-51: "{3}, {T} or {U}, {T}: …" (the Shards) — two costs for
            # one ability; either pays it. Modeled as two activated abilities
            # sharing the effect, the Pemmin's Aura idiom (`extra_specs`):
            # picking which to activate *is* picking the cost.
            halves = [
                segment_line_unsplit(
                    f"{alternative.group(half)}: {act.group('effect')}",
                    allow_spell_effect=allow_spell_effect, provenance=provenance, is_saga=is_saga,
                )
                for half in ("a", "b")
            ]
            if not all(half.claimed and half.spec is not None for half in halves):
                return Segment(raw=raw)
            return Segment(
                raw=raw, spec=halves[0].spec, claimed=True,
                extra_specs=[*halves[0].extra_specs, halves[1].spec, *halves[1].extra_specs],
            )
        if scan_cost_text(act.group("cost")).leftover is not None:
            # ENG-49: a cost fragment no recognizer reads would never be
            # charged, so the ability would be claimed cheaper than printed
            # ("{G}, {T}, Discard a historic card"). Unclaimed instead — the
            # same grammar `game/costs.parse_activation_cost` charges from.
            return Segment(raw=raw)
        effect_text = act.group("effect").strip()
        if (
            MANA_EFFECT_RE.match(effect_text)
            or COLORS_AMONG_PERMANENTS_MANA_RE.match(effect_text)
            or DEVOTION_CHOSEN_COLOR_MANA_RE.match(effect_text)
            or ((counted := COUNTED_CHOSEN_COLOR_MANA_RE.match(effect_text)) is not None
                and parse_amount_phrase(counted.group("amount")) is not None)
        ):
            if MANA_ABILITY_SACRIFICE_X_RE.search(act.group("cost")) and not (
                MANA_ABILITY_X_SUPPORTED_RE.fullmatch(effect_text)
            ):
                # A mana ability announces X only for "Add X mana of any one
                # color[. You gain X life.]" (ENG-51, Springjack Pasture —
                # `ManaAbility.x_scaled`); any other X-sized mana effect would
                # neither scale its sacrifice nor its amount, so stays unclaimed.
                return Segment(raw=raw)
            # Mana ability — covered by the engine's mana model, no spec here.
            return Segment(raw=raw, claimed=True,
                           mana_ability=FIXED_MANA_EFFECT_RE.fullmatch(effect_text) is not None)
        cost_dict: dict[str, Any] = {"text": act.group("cost").strip()}
        # Throne of Eldraine-shaped colour-lock on this ability's own cost —
        # a trailing "Spend only mana of the chosen color to activate this
        # ability." sentence, peeled off the effect body and recorded as a
        # cost flag (`ActivationCost.spend_only_chosen_color`) rather than a
        # (non-existent) effect.
        if SPEND_ONLY_CHOSEN_COLOR_RE.search(effect_text):
            effect_text = SPEND_ONLY_CHOSEN_COLOR_RE.sub("", effect_text).strip()
            cost_dict["spend_only_chosen_color"] = True
        party_reduction = ACTIVATION_COST_REDUCTION_PARTY_RE.search(effect_text)
        if party_reduction is not None:
            effect_text = ACTIVATION_COST_REDUCTION_PARTY_RE.sub("", effect_text).strip()
            cost_dict["dynamic_reduction"] = {
                "count_selector": "creatures_in_your_party",
                "generic_per": int(party_reduction.group("n")),
            }
        else:
            where_x_reduction = ACTIVATION_COST_REDUCTION_WHERE_X_RE.search(effect_text)
            if where_x_reduction is not None:
                selector = activation_cost_reduction_selector(where_x_reduction.group("what"))
                if selector is not None:
                    effect_text = ACTIVATION_COST_REDUCTION_WHERE_X_RE.sub("", effect_text).strip()
                    cost_dict["dynamic_reduction"] = {"count_selector": selector, "generic_per": 1}
            per_reduction = ACTIVATION_COST_REDUCTION_FOR_EACH_RE.search(effect_text)
            if per_reduction is not None:
                selector = activation_cost_reduction_selector(per_reduction.group("what"))
                if selector is not None:
                    effect_text = ACTIVATION_COST_REDUCTION_FOR_EACH_RE.sub("", effect_text).strip()
                    cost_dict["dynamic_reduction"] = {
                        "count_selector": selector,
                        "generic_per": int(per_reduction.group("n")),
                    }
            conditional_reduction = ACTIVATION_COST_REDUCTION_GRAVEYARD_MV_RE.search(effect_text)
            if conditional_reduction is not None:
                effect_text = ACTIVATION_COST_REDUCTION_GRAVEYARD_MV_RE.sub("", effect_text).strip()
                cost_dict["dynamic_reduction"] = {
                    "generic_per": int(conditional_reduction.group("n")),
                    "active_if": {
                        "kind": "distinct_mana_values_in_graveyard_at_least",
                        "min": int(conditional_reduction.group("minimum")),
                    },
                }
            else:
                colored_reduction = ACTIVATION_COST_REDUCTION_COLORED_RE.search(effect_text)
                if colored_reduction is not None:
                    active_if = static_condition(colored_reduction.group("condition"))
                    symbols = re.findall(r"\{([WUBRG])\}", colored_reduction.group("symbols"), re.I)
                    colors = {symbol.upper() for symbol in symbols}
                    if active_if is not None and len(colors) == 1:
                        effect_text = ACTIVATION_COST_REDUCTION_COLORED_RE.sub("", effect_text).strip()
                        cost_dict["dynamic_reduction"] = {
                            "generic_per": int((colored_reduction.group("generic") or "{0}")[1:-1]),
                            "colored": {colors.pop(): len(symbols)},
                            "active_if": active_if,
                        }
                conditional_reduction = ACTIVATION_COST_REDUCTION_CONDITIONAL_RE.search(effect_text)
                if conditional_reduction is not None:
                    active_if = static_condition(conditional_reduction.group("condition"))
                    if active_if is not None:
                        effect_text = ACTIVATION_COST_REDUCTION_CONDITIONAL_RE.sub("", effect_text).strip()
                        cost_dict["dynamic_reduction"] = {
                            "generic_per": int(conditional_reduction.group("n")),
                            "active_if": active_if,
                        }
        tail_markers: list[EffectSpec] = []
        # RULE 602.5d: activation timing qualifies the whole ability, even
        # when the effect body ends in an otherwise branch.
        # The lookbehind alternative keeps the closing quote of a trailing quoted token ability in the body
        # ("... The tokens have "...." Activate only as a sorcery.", Return of the Mole Man).
        sorcery_tail = re.search(r'(?:\.|(?<=\."))\s*activate only as a sorcery\.?$', effect_text, re.I)
        if sorcery_tail is not None:
            effect_text = effect_text[:sorcery_tail.start()].strip()
            tail_markers.extend(parse_effect_body("activate only as a sorcery") or [])
        # RULE 602.2: "Any player may activate this ability [but only as a
        # sorcery]" (Fan Favorite, Feral Hydra, Excavation, the Flailing cycle) —
        # `ActivationCost.any_player_may_activate`, the primitive Mercenaries and
        # Nullhide Ferox were hand-authored on.
        any_player = ANY_PLAYER_MAY_ACTIVATE_RE.search(effect_text)
        if any_player is not None:
            effect_text = effect_text[:any_player.start()].strip()
            cost_dict["any_player_may_activate"] = True
            if any_player.group("sorcery"):
                sorcery = parse_effect_body("activate only as a sorcery")
                if sorcery is None:
                    return Segment(raw=raw)
                tail_markers.extend(sorcery)
        activation_tail = ACTIVATE_ONLY_IF_TRAILING_RE.search(effect_text)
        if activation_tail is not None:
            conds = [
                f"it's the {activation_tail.group('step').lower()} step" if activation_tail.group("step") else None,
                (activation_tail.group("cond") or activation_tail.group("cond2") or "").strip() or None,
            ]
            tail = "activate only if " + " and ".join(c for c in conds if c)
            parsed_tail = parse_effect_body(tail)
            if parsed_tail is None:
                return Segment(raw=raw)
            tail_markers.extend(parsed_tail)
            if activation_tail.group("once"):
                tail_markers.append(EffectSpec(ACTIVATE_ONLY_ONCE_MARKER, {}))
            effect_text = effect_text[:activation_tail.start()].strip()
        nonzero_x = re.search(r"\.\s*x can'?t be 0\.?$", effect_text, re.I)
        if nonzero_x is not None:
            # RULE 107.3a: the printed restriction applies to the announced
            # value, and uses the activation cost's existing minimum.
            if "{x}" not in act.group("cost").lower():
                return Segment(raw=raw)
            effect_text = effect_text[:nonzero_x.start()].strip()
            cost_dict["minimum_x"] = 1
        if re.search(r"\b(?:exile|sacrifice) ~(?:,|$)", raw.split(":", 1)[0].strip(), re.I):
            # RULE 608.2h: with ~ paid as the cost, "it had N counters on it"
            # is ~'s last-known count, captured for its departed visit
            # rather than retained on the exiled card (Lost Isle Calling).
            effect_text = COST_PAID_SOURCE_HAD_RE.sub(r"if ~ has \g<n> or more \g<kind> counters on it,",
                                                       effect_text)
        body, optional = peel_optional(effect_text)
        effects = parse_effect_body(body, reading=ClauseReading(self_subject=True))
        if effects is None:
            # RULE 700.2's *compact* inline modal ("gets +1/-1 or -1/+1
            # until end of turn" — Pemmin's Aura), which the bulleted
            # modal-block grammar can't see. Only tried once the ordinary
            # parse has already failed, so it can never steal a line that
            # already had a reading.
            split = inline_pt_modal_bodies(body)
            if split is None:
                return Segment(raw=raw)
            parsed = [parse_effect_body(half) for half in split]
            if any(half is None for half in parsed):
                return Segment(raw=raw)
            specs = [
                AbilitySpec(
                    "activated",
                    effects=half,
                    cost=dict(cost_dict),
                    optional=optional,
                    raw_text=raw,
                    parser=provenance,
                )
                for half in parsed
            ]
            return Segment(
                raw=raw, spec=specs[0], extra_specs=specs[1:], claimed=True
            )
        effects.extend(tail_markers)
        spec = AbilitySpec(
            "activated",
            effects=effects,
            cost=cost_dict,
            optional=optional,
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def _phase_damage_referents(effects: list[EffectSpec]) -> list[EffectSpec]:
    """RULE 603.2b: a step body's "that player" is the active player.

    Amount wrappers (Festering Wound) can hide damage below ``bind``. Only
    descend into immediate composition, never future granted abilities.
    """
    rewritten = []
    for effect in effects:
        params = dict(effect.params)
        if effect.type == "damage" and params.get("selector") == "event_player":
            params["selector"] = "active_player"
        amount = params.get("amount")
        if effect.type == "bind" and isinstance(amount, dict) and amount.get("of") == "event_player":
            # PAR-215: a count taken "as that player" ("the number of swamps they control") is that same step player.
            params["amount"] = {**amount, "of": "active_player"}
        fields = {"seq": ("effects",), "bind": ("effects",), "if_else": ("then", "else")}.get(effect.type, ())
        for field in fields:
            if isinstance(params.get(field), list):
                children = [EffectSpec(child["type"], child.get("params", {}), condition=child.get("condition")) for child in params[field]]
                params[field] = [child.to_dict() for child in _phase_damage_referents(children)]
        rewritten.append(EffectSpec(effect.type, params, condition=effect.condition))
    return rewritten


#: RULE 511.1: "At end of combat[ on your turn], <effect>" — the end of combat step's beginning-of-step
#: trigger, the same `STEP_BEGIN` shape as `PHASE_TRIGGER_RE`'s "at the beginning of combat". The "on your
#: turn" scope is the ability controller's own end of combat step (``phase_relation``: "you").
_END_OF_COMBAT_TRIGGER_RE = re.compile(
    r"^at end of combat(?P<you> on your turn)?,\s*(?P<body>.+)$", re.IGNORECASE | re.DOTALL,
)


def line_phase_trigger(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    phase_trig = PHASE_TRIGGER_RE.match(raw)
    end_combat_trig = _END_OF_COMBAT_TRIGGER_RE.match(raw) if phase_trig is None else None
    if phase_trig is not None or end_combat_trig is not None:
        if end_combat_trig is not None:
            # RULE 511.1: "at end of combat" is the end of combat step's own beginning-of-step trigger.
            both_mains = False
            step: Optional[str] = END_COMBAT_STEP
            relation = "you" if end_combat_trig.group("you") else None
            raw_body = end_combat_trig.group("body")
        else:
            step_word = (
                phase_trig.group("step_any")
                or phase_trig.group("step_you")
                or phase_trig.group("step_you_each")
                or phase_trig.group("step_both_mains")
                or phase_trig.group("step_combat_you")
                or phase_trig.group("step_combat_opp")
                or phase_trig.group("step_opp")
                or phase_trig.group("step_other")
                or phase_trig.group("step_attached")
                or phase_trig.group("step_enchanted")
                or phase_trig.group("step_chosen")
            )
            both_mains = bool(phase_trig.group("step_both_mains"))
            step = "main1" if both_mains else PHASE_STEP_WORDS.get((step_word or "").lower())
            if (
                phase_trig.group("step_you")
                or phase_trig.group("step_you_each")
                or both_mains
                or phase_trig.group("step_combat_you")
            ):
                relation = "you"
            elif phase_trig.group("step_opp") or phase_trig.group("step_other") or phase_trig.group("step_combat_opp"):
                relation = "not_you"
            elif phase_trig.group("step_attached"):
                relation = "attached_permanent"
            elif phase_trig.group("step_enchanted"):
                relation = "enchanted_player"
            elif phase_trig.group("step_chosen"):
                relation = "chosen_player"
            else:
                relation = None
            raw_body = phase_trig.group("body")
        if step is None:
            return Segment(raw=raw)
        body, optional = peel_optional(raw_body)
        # MEC-46: peel a leading "if another <subtype> entered … this turn,"
        # RULE 603.4 intervening-if into the trigger's own `active_if`.
        phase_active_if: Optional[dict[str, Any]] = None
        phase_self_subject = False
        entered_if = ANOTHER_SUBTYPE_ENTERED_IF_RE.match(body)
        gy_if = CREATURE_CARD_TO_GY_IF_RE.match(body)
        dmg_if = YOU_DEALT_DAMAGE_IF_RE.match(body)
        no_subtype_if = YOU_CONTROL_NO_SUBTYPE_IF_RE.match(body)
        harnessed_if = SOURCE_HARNESSED_IF_RE.match(body)
        noncreature_if = re.match(
            r"^if you'?ve cast a noncreature spell this turn,\s*(?P<rest>.+)$", body, re.I | re.S,
        )
        that_player_hand_if = THAT_PLAYER_HAND_IF_RE.match(body)
        that_player_state_if = THAT_PLAYER_STATE_IF_RE.match(body)
        if harnessed_if is not None:  # MEC-79 / RULE 701.64b
            phase_active_if = {"kind": "source_harnessed"}
            body = harnessed_if.group("rest").strip()
        elif noncreature_if is not None:
            phase_active_if = {"kind": "cast_noncreature_spell_this_turn"}
            body = noncreature_if.group("rest").strip()
        elif entered_if is not None:
            phase_active_if = {
                "kind": "another_subtype_entered_this_turn",
                "subtype": entered_if.group("sub").lower(),
            }
            body = entered_if.group("rest").strip()
        elif gy_if is not None:
            phase_active_if = {"kind": "creature_card_to_graveyard_this_turn"}
            body = gy_if.group("rest").strip()
        elif dmg_if is not None:
            phase_active_if = {
                "kind": "you_dealt_damage_this_turn_at_least",
                "amount": int(dmg_if.group("n")),
            }
            body = dmg_if.group("rest").strip()
        elif no_subtype_if is not None and (
            (no_subtype_if.group("sub1") or no_subtype_if.group("sub2") or "").lower()
            in CONTROL_NO_SUBTYPE_WORDS
        ):
            sub = (no_subtype_if.group("sub1") or no_subtype_if.group("sub2")).lower()
            phase_active_if = {
                "kind": "control_count",
                "selector": f"creatures_you_control_of_type_{sub}",
                "max": 0,
            }
            body = no_subtype_if.group("rest").strip()
        elif that_player_hand_if is not None:
            n = that_player_hand_if.group("n")
            phase_active_if = {
                "kind": "active_player_cards_in_hand_at_most",
                "amount": int(n) if n else 0,
            }
            body = that_player_hand_if.group("rest").strip()
        elif that_player_state_if is not None:
            # PAR-283 / RULE 502.1 + 603.4: "that player" is whoever's step began; the predicate is the shared one
            # about "you", read for that player.
            as_you = re.sub(r"^(has|controls|hasn'?t|didn'?t)\b", lambda m: {
                "has": "have", "controls": "control", "hasn't": "haven't", "hasnt": "haven't", "didn't": "didn't",
                "didnt": "didn't"}[m.group(1).lower()], that_player_state_if.group("pred"), flags=re.I)
            inner = static_condition(f"you {as_you}")
            if inner is not None:
                phase_active_if = {"kind": "as_active_player", "condition": inner}
                body = that_player_state_if.group("rest").strip()
        if phase_active_if is None:
            # RULE 603.4: every recognized leading condition gates both
            # triggering and the complete resolving body, even one sentence.
            gate = PHASE_INTERVENING_IF_RE.match(body)
            gated = static_condition(gate.group("cond")) if gate is not None else None
            if gated is not None:
                phase_active_if = gated
                phase_self_subject = "~" in gate.group("cond")
                body = gate.group("rest").strip()
        phase_reading = ClauseReading(
            self_subject=phase_self_subject,
            attached_subject=relation == "attached_permanent",
        )
        if relation is None:
            them_damage = PHASE_DAMAGE_TO_THEM_RE.match(body)
            if them_damage is not None:
                effects = [EffectSpec("damage", {
                    "amount": int(them_damage.group("n")), "selector": "active_player",
                })]
            else:
                effects = step_player_difference_specs(body) or active_player_phase_body(body) or parse_effect_body(body, reading=phase_reading)
        else:
            effects = step_player_difference_specs(body) or active_player_phase_body(body) or parse_effect_body(body, reading=phase_reading)
        if effects is None and phase_active_if is None:
            # RULE 603.4: any other leading "if `<state>`," of a phase trigger is an intervening
            # if too — read through the shared state-predicate vocabulary (`static_condition`)
            # rather than one regex per phrase. Only tried once the body failed as it stands, so
            # a body some other row already reads (as a per-effect gate) is left as it was.
            gate = PHASE_INTERVENING_IF_RE.match(body)
            gated = static_condition(gate.group("cond")) if gate is not None else None
            if gated is not None:
                phase_active_if = gated
                # A condition that names ``~`` ("if …and ~ isn't a creature, it becomes …", Emergent
                # Haunting) gives a bare "it" in the body its only antecedent: the source.
                active_effects = active_player_phase_body(gate.group("rest").strip())
                # RULE 603.4: this newly recognized body must also test the
                # intervening-if when it resolves (Howling Mine can be tapped
                # in response). The trigger's active_if handles trigger time.
                effects = ([EffectSpec("if_else", {
                    "condition": gated, "then": [e.to_dict() for e in active_effects],
                })] if active_effects is not None else None) or parse_effect_body(
                    gate.group("rest").strip(), reading=phase_reading.but(self_subject="~" in gate.group("cond")),
                )
        if effects is None:
            return Segment(raw=raw)
        effects = _phase_damage_referents(effects)
        if phase_active_if is not None:
            if len(effects) == 1 and effects[0].condition is None:
                # An atomic body already has a single resolution boundary.
                effect = effects[0]
                effects = [EffectSpec(effect.type, effect.params, condition=phase_active_if)]
            else:
                effects = [EffectSpec("seq", {"effects": [effect.to_dict() for effect in effects]}, condition=phase_active_if)]
        steps = EACH_MAIN_PHASE_STEPS if both_mains else (step,)
        phase_specs: list[AbilitySpec] = []
        for one_step in steps:
            trigger: dict[str, Any] = {"event": "STEP_BEGIN", "filter": {"step": one_step}}
            if relation is not None:
                trigger["phase_relation"] = relation
            if phase_active_if is not None:
                trigger["active_if"] = phase_active_if
            phase_specs.append(AbilitySpec(
                "triggered",
                effects=copy.deepcopy(effects) if len(steps) > 1 else effects,
                trigger=trigger,
                optional=optional,
                raw_text=raw,
                parser=provenance,
            ))
        return Segment(raw=raw, spec=phase_specs[0], claimed=True, extra_specs=phase_specs[1:])
    return None


def line_triggered_ability(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    allow_spell_effect = ctx.allow_spell_effect
    provenance = ctx.provenance
    trig = TRIGGER_RE.match(raw)
    if trig is not None:
        cond_text = trig.group("cond")
        # PAR-14: "…for the first time each turn" (Whispering Snitch-shaped)
        # — stripped once here, before any subject-family dispatch below, so
        # every family picks up `AbilitySpec.trigger["limit"]` for free.
        limit_suffix_m = ONCE_PER_TURN_CONDITION_SUFFIX_RE.match(cond_text.strip())
        limit = limit_suffix_m is not None
        if limit_suffix_m is not None:
            cond_text = limit_suffix_m.group("base")

        creature_explores = CREATURE_EXPLORES_TRIGGER_RE.match(cond_text.strip())
        if creature_explores is not None:
            body, optional = peel_optional(trig.group("body"))
            effects = parse_effect_body(body, reading=ClauseReading(group_subject=True))
            if effects is None:
                return Segment(raw=raw)
            condition = {"subject": "group", "type": "creature", "controller": "you"}
            result = creature_explores.group("result")
            if result is not None:
                condition["explore_found_land"] = result.lower() == "land"
            spec = AbilitySpec("triggered", effects=effects, trigger={
                "event": "EXPLORED", "condition": condition,
            }, optional=optional, raw_text=raw, parser=provenance)
            return Segment(raw=raw, spec=spec, claimed=True)

        if NONLAND_CARDS_MILLED_TRIGGER_RE.match(cond_text.strip()):
            body, optional = peel_optional(trig.group("body"))
            effects = parse_effect_body(body, reading=ClauseReading(self_subject=True))
            effects = bind_attack_count(effects, NONLAND_MILLED_COUNT) if effects is not None else None
            if effects is None:
                return Segment(raw=raw)
            effects, body_limit = strip_trigger_once_per_turn_marker(effects)
            spec = AbilitySpec("triggered", effects=effects, optional=optional, raw_text=raw, parser=provenance,
                trigger={"event": "CARDS_MILLED", "condition": {"subject": "player", "scope": "any"},
                         "milled_nonland": True, **({"limit": True} if body_limit or limit else {})})
            return Segment(raw=raw, spec=spec, claimed=True)

        milled_cards = CARDS_MILLED_TO_YOUR_GRAVEYARD_TRIGGER_RE.match(cond_text.strip())
        if milled_cards is not None:
            body, optional = peel_optional(trig.group("body"))
            milled_type = milled_cards.group("type")
            normalized_body = body.strip().rstrip(".").lower()
            if milled_type and normalized_body == "put them onto the battlefield tapped":
                effects = [EffectSpec("return_milled_cards", {
                    "card_type": milled_type.lower(), "tapped": True,
                })]
            elif milled_type and normalized_body == "put 1 of them onto the battlefield":
                effects = [EffectSpec("return_milled_cards", {
                    "card_type": milled_type.lower(), "choose_one": True,
                })]
            elif normalized_body == "each opponent loses 1 life for each card type among those cards":
                effects = [EffectSpec("lose_life_for_milled_card_types", {})]
            else:
                effects = parse_effect_body(body, reading=ClauseReading(self_subject=True))
            if effects is None:
                return Segment(raw=raw)
            trigger: dict[str, Any] = {
                "event": "CARDS_MILLED", "condition": {"subject": "you"},
            }
            if milled_type:
                trigger["milled_card_type"] = milled_type.lower()
            spec = AbilitySpec("triggered", effects=effects, trigger=trigger,
                optional=optional, raw_text=raw, parser=provenance)
            return Segment(raw=raw, spec=spec, claimed=True)

        counter_removed = re.fullmatch(
            r"a (?P<kind>time) counter is removed from (?:~|this card) while it'?s exiled",
            cond_text.strip(), re.IGNORECASE,
        )
        if counter_removed:
            body, optional = peel_optional(trig.group("body"))
            effects = parse_effect_body(body, reading=ClauseReading(self_subject=True))
            if effects is None:
                return Segment(raw=raw)
            spec = AbilitySpec("triggered", effects=effects,
                trigger={"event": "COUNTER_REMOVED", "condition": {"subject": "self"},
                         "filter": {"kind": counter_removed.group("kind").lower(), "zone": "exile"}},
                optional=optional, raw_text=raw, parser=provenance)
            return Segment(raw=raw, spec=spec, claimed=True)

        if LAST_TIME_COUNTER_REMOVED_COND_RE.match(cond_text.strip()):
            # RULE 702.62a: a suspended card's own trigger, fired from exile.
            body, optional = peel_optional(trig.group("body"))
            effects = parse_effect_body(body, reading=ClauseReading(self_subject=True))
            if effects is None:
                return Segment(raw=raw)
            spec = AbilitySpec("triggered", effects=effects,
                trigger={"event": "LAST_TIME_COUNTER_REMOVED", "condition": {"subject": "self"}},
                optional=optional, raw_text=raw, parser=provenance)
            return Segment(raw=raw, spec=spec, claimed=True)

        self_milled = SELF_MILLED_TO_GRAVEYARD_TRIGGER_RE.match(cond_text.strip())
        if self_milled is not None:
            body, optional = peel_optional(trig.group("body"))
            # Narcomoeba's "put it onto the battlefield" is an untargeted
            # self-return, not a fresh RULE 115 target.
            if body.strip().rstrip(".").lower() == "put it onto the battlefield":
                effects = [EffectSpec("return_self_from_graveyard", {})]
            else:
                effects = parse_effect_body(body, reading=ClauseReading(self_subject=True))
                # Creeping Chill's optionality encloses its reflexive
                # exile-and-damage sequence; retain that composition instead
                # of peeling the leading ``you may`` into ability-level
                # optionality (which loses the pronoun's antecedent).
                if effects is None:
                    effects = parse_effect_body(trig.group("body"), reading=ClauseReading(self_subject=True))
                    optional = False
            if effects is None:
                return Segment(raw=raw)
            spec = AbilitySpec("triggered", effects=effects,
                trigger={"event": "CARDS_MILLED", "milled_source": True},
                optional=optional, raw_text=raw, parser=provenance)
            return Segment(raw=raw, spec=spec, claimed=True)

        one_milled_card = ONE_CARD_MILLED_TO_YOUR_GRAVEYARD_TRIGGER_RE.match(cond_text.strip())
        if one_milled_card is not None:
            body, optional = peel_optional(trig.group("body"))
            effects = parse_effect_body(body, reading=ClauseReading(self_subject=True))
            if effects is None:
                return Segment(raw=raw)
            spec = AbilitySpec("triggered", effects=effects, trigger={
                "event": "MILLED_CARD", "condition": {"subject": "you"},
                "milled_card_type": one_milled_card.group("type").lower(),
            }, optional=optional, raw_text=raw, parser=provenance)
            return Segment(raw=raw, spec=spec, claimed=True)

        graveyard_exit = CARDS_LEAVE_YOUR_GRAVEYARD_TRIGGER_RE.match(cond_text.strip())
        if graveyard_exit is not None:
            body, optional = peel_optional(trig.group("body"))
            effects = parse_effect_body(body)
            if effects is None:
                return Segment(raw=raw)
            # RULE 603.2: "This ability triggers only once each turn." (Fang, Fearless l'Cie) is the trigger's limit.
            effects, body_limit = strip_trigger_once_per_turn_marker(effects)
            if not effects:
                return Segment(raw=raw)
            trigger: dict[str, Any] = {
                "event": "CARDS_LEFT_GRAVEYARD",
                "graveyard_owner": "you",
            }
            if limit or body_limit:
                trigger["limit"] = True
            if graveyard_exit.group("types"):
                types = re.split(r" and/or | or ", graveyard_exit.group("types"))
                if not set(types) <= GRAVEYARD_EXIT_TYPES:
                    return Segment(raw=raw)
                trigger["left_graveyard_types"] = types
            if graveyard_exit.group("during"):
                trigger["during_your_turn"] = True
            spec = AbilitySpec(
                "triggered", effects=effects, trigger=trigger, optional=optional,
                raw_text=raw, parser=provenance,
            )
            return Segment(raw=raw, spec=spec, claimed=True)

        card_leaves = CARD_LEAVES_GRAVEYARD_TRIGGER_RE.match(cond_text.strip().replace("\u2019", "'"))
        if card_leaves is not None:
            types = re.split(r" and/or | or ", card_leaves.group("types"))
            if not set(types) <= GRAVEYARD_EXIT_TYPES:
                return Segment(raw=raw)
            body, optional = peel_optional(trig.group("body"))
            effects = parse_effect_body(body)
            if effects is None:
                return Segment(raw=raw)
            effects, body_limit = strip_trigger_once_per_turn_marker(effects)
            if not effects:
                return Segment(raw=raw)
            trigger = {
                "event": "CARD_LEFT_GRAVEYARD",
                "graveyard_owner": "you" if card_leaves.group("owner") == "your" else "opponent",
                "left_graveyard_types": types,
            }
            if limit or body_limit:
                trigger["limit"] = True
            return Segment(raw=raw, spec=AbilitySpec(
                "triggered", effects=effects, trigger=trigger, optional=optional, raw_text=raw, parser=provenance,
            ), claimed=True)

        enters_and_phase = ENTERS_AND_MAIN_PHASE_RE.match(cond_text.strip())
        if enters_and_phase is not None:
            body, optional = peel_optional(trig.group("body"))
            effects = parse_effect_body(body, reading=ClauseReading(self_subject=True))
            if effects is None:
                return Segment(raw=raw)
            effects, body_limit = strip_trigger_once_per_turn_marker(effects)
            eap_limit = limit or body_limit
            eap_specs: list[AbilitySpec] = []
            for trig_dict in (
                {"event": "ENTERS_BATTLEFIELD", "condition": {"subject": "self"}},
                {"event": "STEP_BEGIN", "filter": {"step": "main1"},
                 "phase_relation": "you"},
            ):
                if eap_limit:
                    trig_dict["limit"] = True
                eap_specs.append(AbilitySpec(
                    "triggered",
                    effects=[EffectSpec(e.type, dict(e.params), condition=e.condition)
                             for e in effects],
                    trigger=trig_dict,
                    optional=optional,
                    raw_text=raw,
                    parser=provenance,
                ))
            return Segment(
                raw=raw, spec=eap_specs[0], extra_specs=eap_specs[1:], claimed=True,
            )

        variant_event = variant_trigger_event(cond_text)
        if variant_event is not None:
            body, optional = peel_optional(trig.group("body"))
            effects = parse_effect_body(body)
            if effects is None:
                return Segment(raw=raw)
            effects, body_limit = strip_trigger_once_per_turn_marker(effects)
            limit = limit or body_limit
            # One `AbilitySpec` **per firing condition**, rather than the
            # single list-valued ``event`` `SELF_MULTI_EVENT_RE` emits: the
            # compound plane template's two halves need *different* triggers,
            # since only the upkeep half carries a step filter, and a filter
            # is AND-ed onto the event payload (a `PLANESWALKED_TO` event has
            # no ``step`` key, so a shared filter would fail closed and that
            # half would never fire).
            variant_specs: list[AbilitySpec] = []
            for event_name in (
                variant_event if isinstance(variant_event, list) else [variant_event]
            ):
                trigger = {"event": event_name}
                if event_name == "STEP_BEGIN":
                    trigger["filter"] = {"step": "upkeep"}
                if limit:
                    trigger["limit"] = True
                variant_specs.append(
                    AbilitySpec(
                        "triggered",
                        effects=[EffectSpec(e.type, dict(e.params)) for e in effects],
                        trigger=trigger,
                        optional=optional,
                        raw_text=raw,
                        parser=provenance,
                    )
                )
            return Segment(
                raw=raw,
                spec=variant_specs[0],
                extra_specs=variant_specs[1:],
                claimed=True,
            )
        defender_lands_min: Optional[int] = None
        head_trigger: dict[str, Any] = {}
        composed_head = False
        atk_lands = ATTACKS_DEFENDER_LANDS_RE.match(cond_text.strip())
        atk_most_life = ATTACKS_DEFENDER_MOST_LIFE_RE.match(cond_text.strip())
        multi = SELF_MULTI_EVENT_RE.match(cond_text.strip())
        attached_multi = ATTACHED_MULTI_EVENT_RE.match(cond_text.strip())
        defender_most_life = False
        day_night = re.fullmatch(
            r"(?P<first>day becomes night|night becomes day)(?: or (?P<second>day becomes night|night becomes day))?",
            cond_text.strip(),
        )
        if day_night is not None:
            # RULE 732.1a: this is a global designation, with no object subject.
            event = "DAY_NIGHT_CHANGED"
            condition = {"subject": "global"}
            if day_night.group("second") != {
                "day becomes night": "night becomes day",
                "night becomes day": "day becomes night",
            }[day_night.group("first")]:
                head_trigger = {"filter": {
                    "previous": day_night.group("first").split()[0],
                    "current": day_night.group("first").split()[-1],
                }}
        elif atk_lands is not None:
            event: "str | list[str]" = "ATTACKS"
            condition: Optional[dict[str, Any]] = {"subject": "self"}
            defender_lands_min = int(atk_lands.group("n"))
        elif atk_most_life is not None:
            event = "ATTACKS"
            condition = {"subject": "self"}
            defender_most_life = True
        elif multi is not None:
            event = [multi_event_name(multi.group("v1")), multi_event_name(multi.group("v2"))]
            if not all(event):
                return Segment(raw=raw)  # an unrecognised verb → fail closed
            condition = {"subject": "self"}
        elif attached_multi is not None:
            # "whenever enchanted creature attacks or blocks, …" (RULE
            # 303.4c) — one trigger, two firing events, on the Aura's host.
            event = [
                multi_event_name(attached_multi.group("v1")),
                multi_event_name(attached_multi.group("v2")),
            ]
            if not all(event):
                return Segment(raw=raw)
            condition = {"subject": "attached_permanent"}
        else:
            event = trigger_event(cond_text)
            condition = trigger_condition(cond_text) if event is not None else None
            if event is None or condition is None:
                # PAR-119: the composed object head — subject noun phrase ×
                # verb(s) × tails — for whatever the per-adjective regexes
                # above did not name. Only reached when they declined, so no
                # line they already claim changes.
                head = parse_object_trigger_head(cond_text)
                if head is None:
                    compound = (
                        None if limit else compound_trigger_segment(
                            raw, cond_text, trig.group("body"),
                            allow_spell_effect=allow_spell_effect, provenance=provenance,
                        )
                    )
                    # unrecognised trigger/scope → unclaimed (fail-closed)
                    return compound if compound is not None else Segment(raw=raw)
                event, condition, head_trigger = head.event, head.condition, head.trigger
                composed_head = True
        body, optional = peel_optional(trig.group("body"))
        if event == "DIES":
            delayed_return = delayed_dying_return_specs(body)
            if delayed_return is not None:
                return Segment(raw=raw, spec=AbilitySpec(
                    "triggered", effects=delayed_return,
                    trigger={"event": event, "condition": condition,
                             **({"limit": True} if limit else {}),
                             **head_trigger},
                    optional=optional, raw_text=raw, parser=provenance,
                ), claimed=True)
        # RULE 603.7c / 510.2: "that creature" of "whenever <X> deals combat damage to a creature, destroy that
        # creature at end of combat" (Sosuke, Simic Basilisk's granted ability) is the creature that was dealt
        # the damage, fixed when the delayed ability is created — the firing event's ``target_id``.
        recipient_delayed = (
            composed_head and event == "DAMAGE"
            and (condition or {}).get("subject") in ("self", "group", "attached_permanent")
            and head_trigger.get("filter", {}).get("is_player") is False
            and re.fullmatch(r"(?:destroy|exile) that creature at end of combat\.?", body) is not None
        )
        # A group DAMAGE head aimed at a creature introduces two object
        # referents: the dealer and the recipient.  The delayed-sacrifice
        # body's bare "it"/"that creature" means the recipient on cards such
        # as Sosuke, but the current referent model can only capture the firing
        # subject.  Preserve the legacy row's fail-closed guard during the
        # PAR-131 migration rather than silently destroying the dealer; the
        # "<verb> that creature at end of combat" shape (``recipient_delayed``)
        # is the exception, retargeted to the damaged creature below.
        damage_pronoun = (
            DELAYED_SAC_EXILE_TAIL_RE.fullmatch(body.strip().rstrip(".").strip())
            if composed_head and event == "DAMAGE"
            and (condition or {}).get("subject") == "group"
            and head_trigger.get("filter", {}).get("is_player") is False
            else None
        )
        if damage_pronoun is not None and damage_pronoun.group("obj") and not recipient_delayed:
            return Segment(raw=raw)
        death_counter_branch = (
            LEAVING_COUNTER_IF_ELSE_RE.fullmatch(body)
            if event == "DIES" and (condition or {}).get("subject") == "self"
            else None
        )
        if death_counter_branch is not None:
            kind = death_counter_branch.group("kind").lower()
            effects = [EffectSpec("if_else", {
                "condition": {"kind": "trigger_event_counters", "counter": kind, "min": 1},
                "then": [EffectSpec("exile", {"target_kind": None}).to_dict()],
                "else": [EffectSpec("return_self_to_battlefield", {
                    "under_your_control": True,
                    "extra_counters": {"kind": kind, "count": 1},
                }).to_dict()],
            })]
            return Segment(raw=raw, spec=AbilitySpec(
                "triggered", effects=effects,
                trigger={"event": event, "condition": condition},
                raw_text=raw, parser=provenance,
            ), claimed=True)
        event_counter_gate: Optional[dict[str, Any]] = None
        if event in ("DIES", "LEAVES_BATTLEFIELD"):
            counter_if = LEAVING_COUNTER_INTERVENING_RE.match(body)
            if counter_if is not None:
                kind = counter_if.group("kind")
                if kind in (None, "+1/+1", "-1/-1", "time", "loyalty", "lore", "finality"):
                    event_counter_gate = {
                        **({"kind": kind} if kind else {}),
                        "max" if counter_if.group("no") else "min": (
                            0 if counter_if.group("no") else int(counter_if.group("count") or 1)
                        ),
                    }
                    body = counter_if.group("rest").strip()
        # PAR-120: "that many"/"where x is the number of counters on that
        # creature" behind the gate — see `LEAVING_COUNTER_THAT_MANY_RE`.
        event_counter_amount: Optional[dict[str, Any]] = None
        if event_counter_gate is not None:
            # The measured body is bound as one effect (`bind_x`), so a
            # "you may" behind the gate becomes the ability's own optional —
            # only then; an unmeasured body keeps its parse unchanged.
            measured, measured_optional = (
                peel_optional(body) if not optional else (body, optional)
            )
            where_x = LEAVING_COUNTER_WHERE_X_RE.match(measured)
            if where_x is not None:
                counter = where_x.group("kind") or ""
                body, optional = where_x.group("rest").strip(), measured_optional
                event_counter_amount = {"kind": "trigger_event_counter",
                                        **({"counter": counter} if counter else {})}
            elif LEAVING_COUNTER_THAT_MANY_RE.search(measured):
                body = LEAVING_COUNTER_THAT_MANY_RE.sub("x", measured, count=1)
                optional = measured_optional
                # "that many" names what the gate counted: its own kind, or all.
                counter = event_counter_gate.get("kind") or ""
                event_counter_amount = {"kind": "trigger_event_counter",
                                        **({"counter": counter} if counter else {})}
        # PAR-243: the body of an "is dealt excess damage" head measures that excess (see `EXCESS_WHERE_X_RE`).
        if (event_counter_amount is None and event == "DAMAGE"
                and EXCESS_DAMAGE_KEY in (head_trigger.get("filter") or {}).get("event_minimums", {})):
            measured, measured_optional = peel_optional(body) if not optional else (body, optional)
            where_excess = EXCESS_WHERE_X_RE.match(measured)
            if where_excess is not None:
                body, optional = where_excess.group("rest").strip(), measured_optional
                event_counter_amount = EXCESS_DAMAGE_EVENT_AMOUNT
            elif EXCESS_DAMAGE_EQUAL_RE.search(measured):
                body, optional = EXCESS_DAMAGE_EQUAL_RE.sub("x damage", measured), measured_optional
                event_counter_amount = EXCESS_DAMAGE_EVENT_AMOUNT
        # PAR-98: Meanders Guide's optional tap is the antecedent for a
        # following "When you do" trigger.  Keep the pair together before
        # the ordinary optional wrapper can turn it into two unrelated
        # clauses.
        # `peel_optional` deliberately leaves this "you may" in place (its
        # guard protects `MAY_EFFECT_THEN_ANTECEDENT_PHRASES` shapes), so
        # peel it here — the optionality wraps the whole tap-then-return pair.
        reflexive_tap = REFLEXIVE_TAP_PEEL_RE.match(body)
        if cond_text.strip() == "~ attacks" and reflexive_tap is not None:
            body = reflexive_tap.group("rest")
            optional = True
            effects = parse_effect_body(body, reading=ClauseReading(self_subject=True))
            if effects is None:
                return Segment(raw=raw)
            return Segment(raw=raw, spec=AbilitySpec(
                "triggered", effects=effects,
                trigger={"event": "ATTACKS", "condition": {"subject": "self"}},
                optional=optional, raw_text=raw, parser=provenance,
            ), claimed=True)
        # RULE 603.4 intervening-if prefix on an "~ attacks a player"
        # trigger — "…, if no opponent has more life than that player, …"
        # (Guild Artisan &c). Only for a self-subject ATTACKS trigger;
        # strip it, parse the rest, and gate the trigger on the attacked
        # player's life via `attacked_player_has_lowest_life`.
        attacked_lowest_life = False
        if event == "ATTACKS" and condition == {"subject": "self"}:
            low_m = ATTACKED_PLAYER_LOWEST_LIFE_IF_RE.match(body.strip())
            if low_m is not None:
                attacked_lowest_life = True
                body = low_m.group("rest")
        # PAR-120: "whenever a creature attacks 1 of your opponents, **that
        # player** loses/gains N life." (Calculating Lich). Caught here,
        # before the generic group-subject dispatch below: that dispatch's
        # own "its controller"/"that player" family (`_group_its_
        # controller_loses_life`) means the *attacking* creature's
        # controller (RULE 603.1's own group referent, "entering"), which
        # is the wrong side of this attack — RULE 506.4's defending player
        # is a distinct event field, so this shape needs its own referent
        # rather than reusing that one under the same printed pronoun.
        if (condition or {}).get("attacks_opponent"):
            attacked_player_life = ATTACKS_OPPONENT_THAT_PLAYER_LIFE_RE.match(body.strip())
            if attacked_player_life is not None:
                verb = attacked_player_life.group("verb")
                effect_type = "lose_life" if verb == "loses" else "gain_life"
                effects = [EffectSpec(effect_type, {
                    "amount": int(attacked_player_life.group("n")),
                    "player": {"of": "attacked_player"},
                })]
                return Segment(raw=raw, spec=AbilitySpec(
                    "triggered", effects=effects, trigger={"event": event, "condition": condition},
                    raw_text=raw, parser=provenance,
                ), claimed=True)
        # "When ~ enters, **it** fights …": with the source as the trigger's
        # own subject, a bare "it" in the body is the source — anything else
        # (a group subject, an attached permanent) leaves the pronoun
        # ambiguous, so only this scope unlocks it. MEC-28: "whenever a
        # creature you control attacks alone, … that creature …" is the
        # `{"subject": "group"}` sibling — `condition` may carry extra keys
        # (``controller``/``type``/…) alongside it, so this reads the key
        # rather than requiring an exact dict match the way ``self_subject``
        # does above.
        copy_departed = (
            LEAVING_COUNTER_COPY_RE.fullmatch(body)
            if event_counter_gate is not None else None
        )
        dies_token_copy = (
            event == "DIES" and (condition or {}).get("subject") == "self"
            and SELF_DIES_TOKEN_COPY_RE.fullmatch(body.strip().rstrip(".")) is not None
        )
        delayed_copy = (
            LEAVING_COUNTER_DELAYED_COPY_RE.fullmatch(body)
            if event_counter_gate is not None and (condition or {}).get("subject") == "self"
            else None
        )
        create_transfer = (
            LEAVING_COUNTER_CREATE_TRANSFER_RE.fullmatch(body)
            if event_counter_gate is not None and (condition or {}).get("subject") == "self"
            else None
        )
        return_without_abilities = (
            LEAVING_COUNTER_RETURN_LOSE_RE.fullmatch(body)
            if event_counter_gate is not None and (condition or {}).get("subject") == "self"
            else None
        )
        if create_transfer is not None:
            created = parse_effect_body(create_transfer.group("create"))
            if not created or len(created) != 1 or created[0].type != "create_token":
                return Segment(raw=raw)
            effects = [*created, EffectSpec("transfer_event_counters", {
                "target_kind": "created",
            })]
        elif return_without_abilities is not None:
            effects = [EffectSpec("return_self_to_battlefield", {
                "lose_all_abilities": True,
            })]
        elif delayed_copy is not None:
            # The end-step trigger no longer sees the DIES event, so this
            # ability pins the departed object and half its counters now
            # (RULE 603.7c, RULE 107.2 rounding down) for the delayed copy.
            kind = delayed_copy.group("kind")
            effects = [EffectSpec("bind", {
                "name": "id", "amount": {"kind": "trigger_event", "field": "instance_id"},
                "effects": [EffectSpec("bind", {
                    "name": "half",
                    "amount": {"kind": "trigger_event_counter", "counter": kind, "divide": 2},
                    "effects": [EffectSpec("create_delayed_trigger", {
                        "step": "end", "scope": "any",
                        "effects": [EffectSpec("copy_permanent", {
                            "count": 1, "target_kind": None, "target_instance_id": "$id",
                            "enter_counters": {kind: "$half"},
                        }).to_dict()],
                    }).to_dict()],
                }).to_dict()],
            })]
            event_counter_amount = None  # measured here, not by `bind_x`
        elif dies_token_copy:
            # RULE 700.4 / 707.2 / 603.10a: a self DIES trigger's "it" is the dying permanent itself; the copy is of
            # its last-known copiable values (the DIES event's ``copiable_card``), never of its graveyard card.
            effects = [EffectSpec("copy_permanent", {"count": 1, "target_kind": None, "referent": "trigger_event"})]
        elif copy_departed is not None:
            # RULE 400.7: a dying object's snapshot is the copy referent;
            # the ability source may have changed zones before resolution.
            effects = [EffectSpec("copy_permanent", {
                "count": int(copy_departed.group("count")), "target_kind": None,
                "referent": "trigger_event",
            })]
        else:
            # A batch (RULE 603.2c) has no one firing object, so its body gets no
            # single-object pronoun reading at all ("it" stays unclaimed).
            if (condition or {}).get("subject") == "group" and not CARD_INTRODUCER_RE.search(body):
                # "whenever a creature you control dies, return **that card** to its owner's
                # hand": the card is the object that fired the trigger, the same referent "it" is.
                body = re.sub(r"\bthat card\b(?!')", "it", body)
            group_pronoun_names_source = (
                (condition or {}).get("subject") == "group" and pronoun_continues_source(body.lower())
            )
            # "~ or another creature you control enters, **that creature** gets +2/+2": whichever of
            # the two fired it, a *named* pronoun is that object; a bare "it" could as well be "~", so
            # the composed head still refuses it.
            composed_names_firing = (
                (condition or {}).get("subject") == "self_or_group"
                and BARE_IT_RE.search(body.lower()) is None
                and not pronoun_continues_source(body.lower())
            )
            body_reading = ClauseReading(
                # "put a +1/+1 counter on ~. It gains flying": the "it" is the source the
                # sentence just named, so the body reads as a self-subject one.
                self_subject=(condition or {}).get("subject") in ("self", "you", "player")
                or group_pronoun_names_source
                # RULE 603.8: a state trigger fires on no object, so its bare "it" can only be the source.
                or event == "STATE_CHECK",
                group_subject=bool(
                    ((condition or {}).get("subject") == "group" or composed_names_firing)
                    and event != "EVENT_BATCH" and "contributors" not in head_trigger
                    and not group_pronoun_names_source
                ),
                attached_subject=(condition or {}).get("subject") == "attached_permanent",
            )
            recipient_destroy = (
                composed_head and event == "DAMAGE"
                and (condition or {}).get("subject") in ("self", "attached_permanent")
                and head_trigger.get("filter", {}).get("is_player") is False
                and re.fullmatch(
                    r"destroy (?:that creature|it)(?:\. (?:it|the creature|that creature) can't be regenerated)?\.?", body,
                ) is not None
            )
            block_destroy = (
                set(event if isinstance(event, list) else [event]) <= {"BLOCKS", "BECOMES_BLOCKED"}
                and bool(head_trigger.get("related_filter"))
                and (condition or {}).get("subject") in ("self", "attached_permanent")
                and re.fullmatch(r"destroy (?:it|that creature)(?:\. it can't be regenerated)?\.?", body) is not None
            )
            attached_destroy = (
                (condition or {}).get("subject") == "attached_permanent"
                and event == "BECOMES_TARGET"
                and re.fullmatch(r"destroy (?:it|that creature)(?:\. it can't be regenerated)?\.?", body) is not None
            )
            if recipient_destroy or attached_destroy or block_destroy:
                body_reading = ClauseReading(previous_subject=True)
            effects = (
                event_player_body(body)
                if isinstance(event, str) and event in ATTACKING_PLAYER_EVENTS
                and (condition or {}).get("subject") == "player" else None
            ) or parse_effect_body(body, reading=body_reading)
            if (recipient_destroy or attached_destroy) and effects is not None:
                effects = [EffectSpec("trigger_subject_referent", {
                    "event_key": "target_id" if recipient_destroy else "instance_id",
                }), *effects]
            if recipient_delayed and effects is not None:
                effects = retarget_damaged_creature_riders(effects)
            if block_destroy and effects is not None:
                effects = [EffectSpec(e.type, {
                    **{k: v for k, v in e.params.items() if k != "previous_subject"},
                    "trigger_related": True, "related_filter": dict(head_trigger["related_filter"]),
                }, condition=e.condition) for e in effects]
            if (
                effects is None and set(event if isinstance(event, list) else [event]) <= {"BLOCKS", "BECOMES_BLOCKED"}
            ):
                effects = block_related_body(body, head_trigger, (condition or {}).get("subject"))
            count_amount = HEAD_COUNT_AMOUNTS.get(event) if isinstance(event, str) else None
            if effects is None and count_amount is not None and THAT_MANY_RE.search(body):
                # "put that many +1/+1 counters on ~" off a counting head: the body read
                # with a literal X (every X-capable verb already takes one), X bound to
                # the head's own count — not one "that many" row per verb.
                x_effects = parse_effect_body(THAT_MANY_RE.sub("x", body), reading=body_reading)
                effects = bind_x(x_effects, count_amount) if x_effects else None
        if effects is None:
            return Segment(raw=raw)
        if event_counter_amount is not None:
            effects = bind_x(effects, event_counter_amount)
            if effects is None:
                return Segment(raw=raw)
        if event == "DAMAGE" and (condition or {}).get("recipient") and (condition or {}).get("subject") == "group":
            # PAR-243: "target other than that permanent" under "a permanent is dealt damage" is the damaged one.
            effects = stamp_recipient_exclusion(effects)
        if (composed_head and event == "DAMAGE" and (condition or {}).get("subject") == "group"
                and head_trigger.get("filter", {}).get("is_player") is True
                and THAT_PLAYER_BODY_RE.match(body.strip())):
            effects = retarget_that_player_to_damaged(effects)
            if effects is None:
                return Segment(raw=raw)
        if (event in DEFENDING_PLAYER_COMBAT_EVENTS
                and (condition or {}).get("subject") in ("group", "self_or_group", "attached_permanent")
                and THAT_PLAYER_BODY_RE.match(body.strip())):
            # PAR-315 / RULE 508.1b: "that player" under an attack / blocked head is the attacked player, not the
            # firing creature's controller the group dispatch would read.
            effects = retarget_that_player_to_attacked(effects)
            if effects is None:
                return Segment(raw=raw)
        if (condition or {}).get("subject") == "attached_permanent":
            # RULE 603.3: "destroy it" names the firing host, even if the Aura moves before resolution.
            effects = [
                EffectSpec("trigger_subject_referent", {
                    "event_key": GROUP_SUBJECT_KEY_SENTINEL,
                    "effects": [{"type": "destroy", "params": {
                        **{k: v for k, v in e.params.items() if k != "target_kind"}, "previous_subject": True,
                    }}],
                }, condition=e.condition)
                if e.type == "destroy" and e.params.get("target_kind") == "attached_permanent" else e
                for e in effects
            ]
        stamped = stamp_group_pronoun(condition, body, effects)
        if stamped is None:
            return Segment(raw=raw)
        effects = stamped
        if composed_head and group_it_would_hit_source(condition, body, effects):
            return Segment(raw=raw)
        if event == "PLAYER_ATTACKED" and reads_event_amount(effects):
            # "Whenever one or more creatures you control attack, … that much/many" (Grand Warlord Radha, Ohran
            # Viper-shaped): `PLAYER_ATTACKED` fires once per defender and carries no amount, so the count is read off
            # the whole declaration instead (`ATTACKERS_DECLARED`). A group-filtered head has no equivalent: fail closed.
            if condition.get("group_filter"):
                return Segment(raw=raw)
            event = "ATTACKERS_DECLARED"
            head_trigger = {"attackers_declared": {"filter": {"card_type": "creature"}, "min": 1}}
        if event in ("ATTACKERS_DECLARED", "ATTACKERS_AT_DEFENDER"):
            effects = bind_attack_count(effects)
            if effects is None:
                return Segment(raw=raw)
        if event != "EVENT_BATCH" and "'batch_members'" in repr(effects):
            return Segment(raw=raw)  # "them" names a batch only under a batch head
        if event == "EVENT_BATCH":
            if "trigger_subject" in repr(effects) or "__group_subject__" in repr(effects):
                return Segment(raw=raw)  # no single firing object to name
            effects = bind_attack_count(effects, BATCH_COUNT_AMOUNT)
            if effects is None:
                return Segment(raw=raw)
        if composed_head:
            effects = retarget_block_relation(event, head_trigger, effects)
        if f"'{NEEDS_BLOCK_HEAD}': True" in repr(effects):
            return Segment(raw=raw)  # "that creature" of a block relation, under a head with no block to name
        if (
            "'trigger_related': True" in repr(effects) or "'capture': 'trigger_related'" in repr(effects)
        ) and "'related_filter'" not in repr(effects):
            return Segment(raw=raw)  # "that creature" of a block relation, under a head that has no other side
        effects, body_limit = strip_trigger_once_per_turn_marker(effects)
        limit = limit or body_limit
        # RULE 603.4: the crew-history condition gates the entire triggered ability,
        # including subsequent sentences, both at triggering and at resolution.
        leading_state = ETB_INTERVENING_IF_RE.match(body)
        state_gate = static_condition(leading_state['cond']) if leading_state is not None else None
        counter_gate = None
        if leading_state is not None and (condition or {}).get('subject') == 'self':
            counter_gate = parse_referent_condition(leading_state['cond'].replace('~', 'it'))
            if counter_gate is not None and counter_gate.get('kind') != 'source_counters':
                counter_gate = None
        if counter_gate is not None:
            state_gate = counter_gate
        # RULE 603.4 / 111.1: "when ~ dies, if it isn't a token, ..." -- the source's own token status gates the trigger
        # itself, so a token never puts the ability on the stack (the body keeps the resolution-time check).
        token_gate = state_gate if state_gate in SELF_TOKEN_STATUS_GATES and (condition or {}).get('subject') == 'self' else None
        # RULE 603.4 / 603.8: a state trigger's "if ~ is an enchantment" is checked as it triggers. Without that gate the
        # still-true state would put the ability on the stack again after every resolution (Hidden Predators).
        state_trigger_gate = event == "STATE_CHECK" and state_gate is not None and state_gate.get('kind') == 'is_card_type'
        if state_gate is not None and (state_gate.get('kind') in ('crewed_by_filter', 'you_have_most', 'you_have_fewest') or counter_gate is not None or token_gate is not None or state_trigger_gate):
            head_trigger = {**head_trigger, 'active_if': state_gate}
            effects = [EffectSpec('seq', {'effects': [
                EffectSpec(e.type, e.params, condition=None if e.condition == state_gate else e.condition).to_dict()
                for e in effects
            ]}, condition=state_gate)]
        intervening = etb_intervening_if(event, condition, body)
        if intervening is not None:
            head_trigger = {**head_trigger, "active_if": intervening}
            # What was spent to cast the permanent is history: it cannot change between the trigger event and the
            # resolution, so the second RULE 603.4 check can only agree with the first — and, read off a source that
            # has since left the battlefield (a new object, RULE 400.7, with nothing spent), it would wrongly
            # disagree where last-known information (RULE 608.2h) says it was spent. One check, at trigger time.
            if intervening.get("kind") == "mana_color_spent_to_cast_at_least":
                effects = [
                    EffectSpec(e.type, e.params, condition=None if e.condition == intervening else e.condition)
                    for e in effects
                ]
        spec = AbilitySpec(
            "triggered",
            effects=effects,
            trigger={
                "event": event,
                "condition": condition,
                **({"limit": True} if limit else {}),
                **({"defender_controls_lands_at_least": defender_lands_min}
                   if defender_lands_min else {}),
                **({"attacked_player_has_lowest_life": True}
                   if attacked_lowest_life else {}),
                **({"attacked_player_has_most_life": True}
                   if defender_most_life else {}),
                **({"event_counter_gate": event_counter_gate}
                   if event_counter_gate is not None else {}),
                **head_trigger,
                # RULE 605.1b: a trigger off a mana ability whose body only adds mana is
                # itself a mana ability — it resolves at once, never on the stack.
                **({"mana_ability": True}
                   if event == "TAPPED_FOR_MANA" and effects
                   and all(e.type in MANA_ADDING_EFFECTS for e in effects) else {}),
            },
            optional=optional,
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


# No trigger wrapper. On a *permanent*, "As ~ enters, choose a creature
# type/color" (RULE 601.2b) is a characteristic-defining choice made as
# part of entering — an ``enter_replacement`` ability (RULE 614.1c/
# 614.12's family, not a triggered ability and not `static_effect_specs`'
# standing-continuous-ability shape either), tried first since it's a
# narrower, closed pair of clauses.
def line_permanent_standing_line(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    allow_spell_effect = ctx.allow_spell_effect
    provenance = ctx.provenance
    if not allow_spell_effect:
        enter_choice = enter_choice_specs(raw)
        if enter_choice is not None:
            spec = AbilitySpec(
                "enter_replacement", effects=enter_choice, raw_text=raw, parser=provenance
            )
            return Segment(raw=raw, spec=spec, claimed=True)
        # A standing "Creatures you control get +1/+1" / "Goblins you
        # control have haste" is a static continuous ability (RULE 613), not
        # a resolve-time effect — try that before giving up.
        static = static_effect_specs(raw)
        if static is not None:
            spec = AbilitySpec(
                standing_ability_kind(static), effects=static, raw_text=raw, parser=provenance
            )
            return Segment(raw=raw, spec=spec, claimed=True)
        # A standing "if X would Y, Z instead" line (RULE 614/616) is a
        # replacement effect, not a static continuous ability — tried after
        # `static_effect_specs` (the two never overlap in shape) before
        # giving up.
        replacement = replacement_clause_specs(raw)
        if replacement is not None:
            spec = AbilitySpec(
                "replacement", effects=replacement, raw_text=raw, parser=provenance
            )
            return Segment(raw=raw, spec=spec, claimed=True)
        return Segment(raw=raw)  # permanent bare imperative → unclaimed
    return None


# RULE 601.2f "This spell costs {N} less to cast if `<condition>`."/
# "…for each attacking creature [you control]." — a spell's own self
# cost reduction, printed on an instant/sorcery rather than a
# permanent. `continuous.self_cost_reduction_for` already reads this
# off *any* object's `static_effects` regardless of zone (Ghostfire
# Slice's own hand-authored entry proves the engine side works) — the
# only missing piece was ever reaching `static_effect_specs` at all
# for a card where `allow_spell_effect` is true, since every clause
# below this point is otherwise routed to the resolve-time
# `spell_effect` parse instead. Scoped to a pure ``cost_reduction``
# result so an unrelated static-shaped false match can't misfile a
# genuine resolve-time clause here.
def line_spell_cost_static(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    allow_spell_effect = ctx.allow_spell_effect
    provenance = ctx.provenance
    if allow_spell_effect:
        cost_static = static_effect_specs(raw)
        if cost_static is not None and (
            all(spec.type == "cost_reduction" and spec.params.get("affects") == "self" for spec in cost_static)
            or all(spec.type == "grant_graveyard_to_library_replacement" for spec in cost_static)
        ):
            spec = AbilitySpec("static", effects=cost_static, raw_text=raw, parser=provenance)
            return Segment(raw=raw, spec=spec, claimed=True)
    return None


# A resolve-time effect (instant/sorcery only).
def line_spell_effect_imperative(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    body, optional = peel_optional(raw)
    effects = parse_effect_body(body)
    if effects is None:
        return Segment(raw=raw)
    spec = AbilitySpec(
        "spell_effect",
        effects=effects,
        optional=optional,
        raw_text=raw,
        parser=provenance,
    )
    return Segment(raw=raw, spec=spec, claimed=True)
