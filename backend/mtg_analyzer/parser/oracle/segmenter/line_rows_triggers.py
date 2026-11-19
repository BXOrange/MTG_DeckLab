"""Segmenter: line rows triggers (split from `segmenter.py` by PAR-172's method, ENG-59)."""

from __future__ import annotations

import re
from ..catalogue.clause_reading import ClauseReading
from typing import Any, Optional
from ..catalogue.cost_text import scan_cost_text
from ..catalogue.spell_phrase import parse_spell_phrase
from ..catalogue.effect_rows.draw_discard_cast import CYCLING_XX_TOKEN_RE, cycling_xx_token
from ..catalogue.keywords import EQUIP_DASH_COST_RE, EQUIP_ONCE_EACH_TURN_RE
from ..spec import AbilitySpec, EffectSpec, ParserProvenance
from .segment_types import Segment
from .optional_peel import peel_optional
from .effect_body import parse_effect_body
from .keyword_lines import is_keyword_line, segment_keyword_labeled_ability
from .segment_forms import segment_line
from .line_types import LineContext
from .trigger_heads import (
    ATTACK_MELD_TRIGGER_RE,
    BASIC_LAND_TYPE_SINGULAR,
    CAST_SPELL_COLOR_WORDS,
    CAST_SPELL_NOT_THEIR_TURN_TRIGGER_RE,
    CAST_SPELL_NO_MANA_TRIGGER_RE,
    CAST_SPELL_ORDINAL_WORDS,
    CAST_SPELL_SHARES_TYPE_SOURCE_TRIGGER_RE,
    CAST_SPELL_TARGETS_PERMANENT_TRIGGER_RE,
    CAST_SPELL_TARGETS_SOURCE_TRIGGER_RE,
    CAST_THIS_SPELL_TRIGGER_RE,
    CAST_TRIGGER_COMPOSED_RE,
    CAST_TWO_COLOR_SPELL_TRIGGER_RE,
    CAUSED_DISCARD_REPLACEMENT_RE,
    CONTROL_NONE_MATCHING_RE,
    CONTROL_NONE_SACRIFICE_RE,
    COUNTER_FREE_SPELL_RE,
    CYCLE_TRIGGER_RE,
    DOCTOR_OR_COMPANION_CREATURE_CAST_TRIGGER_RE,
    DRAW_CARD_TRIGGER_NTH_RE,
    DRAW_TRIGGER_PLAIN_RE,
    ENTERS_IF_CAST_RE,
    ENTERS_IF_MADNESS_PAID_RE,
    ETB_AND_CAST_TRIGGER_RE,
    EXERT_BARE_RE,
    EXERT_PLAYER_TRIGGER_RE,
    EXERT_TRIGGER_RE,
    MAGECRAFT_RE,
    MELD_TRIGGER_RE,
    OPPONENT_CAUSED_DISCARD_TRIGGER_RE,
    PHASE_STEP_WORDS,
    REVEAL_FIRST_DRAW_RE,
    SACRIFICE_TYPE_TRIGGER_RE,
    SELF_DISCARD_TRIGGER_RE,
    TAP_FOR_MANA_TRIGGER_RE,
    cast_spell_trigger_condition,
    cast_trigger_segment,
    caused_discard_effects,
    strip_trigger_once_per_turn_marker,
)
from .activation_clauses import PLAY_WITH_TOP_REVEALED_RE
from .referents import EQUIP_RIDER_RE

def line_neither_day_nor_night(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    if re.fullmatch(
        r"if it'?s neither day nor night, it becomes day as (?:~|this (?:creature|artifact|enchantment)|[a-z][a-z' -]+) enters\.?",
        raw,
        re.I,
    ):
        return Segment(
            raw=raw,
            spec=AbilitySpec(
                "enter_replacement", [EffectSpec("establish_day_on_entry", {})],
                raw_text=raw, parser=provenance,
            ),
            claimed=True,
        )
    return None


# PAR-28: "Boast/Exhaust/Forecast/Power-up/Solved/Max speed — [ability]".
# Checked *before* `is_keyword_line`, since `_KEYWORD_TOKEN_RE`'s greedy
# `.*$` would otherwise claim the whole "<keyword> — <cost>: <effect>"
# line as a bare keyword line (producing no ability at all).
def line_kw_labeled(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    allow_spell_effect = ctx.allow_spell_effect
    provenance = ctx.provenance
    is_saga = ctx.is_saga
    kw_labeled = segment_keyword_labeled_ability(
        raw, allow_spell_effect=allow_spell_effect, provenance=provenance, is_saga=is_saga
    )
    if kw_labeled is not None:
        return kw_labeled
    return None


# BUG-1: "Equip—<non-mana cost>[. Activate only once each turn.]" is a keyword line only when the cost grammar fully represents
# the cost (RULE 602.1, `costs.parse_activation_cost`); a choice cost ("Pay {3} or discard a card") stays unclaimed, never free.
def line_equip_dash(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    equip_dash = EQUIP_DASH_COST_RE.fullmatch(raw.strip())
    if equip_dash is not None:
        if scan_cost_text(equip_dash.group("cost").strip()).leftover is None:
            return Segment(raw=raw, claimed=True, keyword_line=True)
        return Segment(raw=raw, claimed=False)
    return None


# BUG-1: an "Equip abilities you activate …" static, or an "Equip {N}. <rider>" sentence, is not a bare equip cost. The keyword
# token's greedy `.*$` would claim it whole and drop the rider, so it falls through to the static handlers instead.
def line_equip_once_each_turn(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    if is_keyword_line(raw) and (EQUIP_RIDER_RE.match(raw) is None or EQUIP_ONCE_EACH_TURN_RE.fullmatch(raw)):
        return Segment(raw=raw, claimed=True, keyword_line=True)
    return None


# PAR-79 fifth increment: see `ETB_AND_CAST_TRIGGER_RE`'s own docstring
# — split before any single-trigger regex gets a look, so a compound
# "enters and whenever you cast" line always goes through this path
# rather than falling through to the composed cast head (whose own
# ``^(?:whenever|when) <actor>`` anchor wouldn't match this line's leading
# "when ~ enters and " anyway, but the ordering is deliberate).
def line_etb_and_cast(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    allow_spell_effect = ctx.allow_spell_effect
    provenance = ctx.provenance
    etb_and_cast = ETB_AND_CAST_TRIGGER_RE.match(raw)
    if etb_and_cast is not None:
        body = etb_and_cast.group("body").strip()
        cast_clause = etb_and_cast.group("cast_clause").strip()
        etb_seg = segment_line(
            f"when ~ enters, {body}",
            allow_spell_effect=allow_spell_effect, provenance=provenance,
        )
        cast_seg = segment_line(
            f"whenever {cast_clause}, {body}",
            allow_spell_effect=allow_spell_effect, provenance=provenance,
        )
        if etb_seg.spec is not None and cast_seg.spec is not None:
            return Segment(raw=raw, spec=etb_seg.spec, extra_specs=[cast_seg.spec], claimed=True)
        return Segment(raw=raw)
    return None


#: PAR-207 (RULE 603.2 / 603.1): one printed sentence naming two trigger conditions that share one body is two
#: independent triggered abilities -- "When you cast or cycle ~" is "when you cast this spell" plus "when you cycle
#: this card" (Drownyard Lurker, Warped Tusker), "When ~ enters and when you sacrifice it" is "when ~ enters" plus
#: "when you sacrifice ~" (Carrot Cake, Heaped Harvest). Each half is re-segmented as a line of its own, so it gets
#: exactly the head and body reading a single-condition line would.
_SPLIT_HEAD_ROWS: tuple[tuple["re.Pattern[str]", tuple[str, ...]], ...] = (
    (re.compile(r"^when you cast or cycle ~,\s*(?P<body>.+)$", re.IGNORECASE | re.S),
     ("when you cast this spell, {body}", "when you cycle this card, {body}")),
    (re.compile(r"^when ~ dies and when you discard this card,\s*(?P<body>.+)$", re.IGNORECASE | re.S),
     ("when ~ dies, {body}", "when you discard this card, {body}")),
    (re.compile(r"^when ~ enters and when you sacrifice (?:it|~),\s*(?P<body>.+)$", re.IGNORECASE | re.S),
     ("when ~ enters, {body}", "when you sacrifice ~, {body}")),
)


def line_split_heads(ctx: LineContext) -> Optional[Segment]:
    for pattern, templates in _SPLIT_HEAD_ROWS:
        m = pattern.match(ctx.raw)
        if m is None:
            continue
        parts = [
            segment_line(
                template.format(body=m.group("body").strip()),
                allow_spell_effect=ctx.allow_spell_effect, provenance=ctx.provenance,
            )
            for template in templates
        ]
        if any(part.spec is None or not part.claimed for part in parts):
            return Segment(raw=ctx.raw)
        specs = [spec for part in parts for spec in (part.spec, *part.extra_specs)]
        return Segment(raw=ctx.raw, spec=specs[0], extra_specs=specs[1:], claimed=True)
    return None


def line_play_with_top_revealed(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    if PLAY_WITH_TOP_REVEALED_RE.match(raw):
        return Segment(raw=raw, claimed=True)  # informational-only, no spec (see docstring)
    return None


def line_meld_trig(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    meld_trig = MELD_TRIGGER_RE.match(raw)
    if meld_trig is not None:
        step = PHASE_STEP_WORDS.get(meld_trig.group("step").lower(), meld_trig.group("step").lower())
        spec = AbilitySpec(
            "triggered",
            effects=[EffectSpec("meld", {
                "partner_name": meld_trig.group("partner").strip(),
                "result_name": meld_trig.group("result").strip(),
            })],
            trigger={"event": "STEP_BEGIN", "filter": {"step": step}, "phase_relation": "you"},
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def line_attack_meld(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    attack_meld = ATTACK_MELD_TRIGGER_RE.match(raw)
    if attack_meld is not None:
        before = parse_effect_body(attack_meld.group("before"))
        if before is None:
            return Segment(raw=raw)
        before.append(EffectSpec("meld", {
            "partner_name": attack_meld.group("partner").strip(),
            "result_name": attack_meld.group("result").strip(),
            "tapped_attacking": True,
        }))
        return Segment(raw=raw, spec=AbilitySpec(
            "triggered", effects=before,
            trigger={"event": "PLAYER_ATTACKED", "condition": {"subject": "you"}},
            raw_text=raw, parser=provenance,
        ), claimed=True)
    return None


def line_wordy(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    wordy = re.fullmatch(r"whenever you cast a wordy spell, (.+)", raw)
    if wordy is not None:
        effects = parse_effect_body(wordy[1])
        if effects is None:
            return Segment(raw=raw)
        return Segment(raw=raw, spec=AbilitySpec(
            "triggered", effects=effects,
            trigger={"event": "SPELL_CAST", "condition": {"subject": "group", "controller": "you", "type": "permanent"},
                     "printed_rules_lines_at_least": 4},
            raw_text=raw, parser=provenance), claimed=True)
    return None


def line_magecraft(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    magecraft = MAGECRAFT_RE.match(raw)
    if magecraft is not None:
        effects = parse_effect_body(magecraft.group("body"))
        if effects is None:
            return Segment(raw=raw)
        spec = AbilitySpec(
            "triggered",
            effects=effects,
            trigger={
                "event": "SPELL_CAST",
                "condition": {"subject": "group", "type": "permanent", "controller": "you", "other": False},
                "spell_subtype_any": ["instant", "sorcery"],
            },
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def line_counter_free_spell(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    if COUNTER_FREE_SPELL_RE.match(raw):
        spec = AbilitySpec(
            "triggered",
            effects=[EffectSpec("counter", {"target_from_trigger_event": "instance_id"})],
            trigger={
                "event": "SPELL_CAST",
                "condition": {"subject": "group"},
                "spell_no_mana_spent": True,
            },
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def line_enters_if_cast(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    enters_if_cast = ENTERS_IF_CAST_RE.match(raw)
    if enters_if_cast is not None:
        body, optional = peel_optional(enters_if_cast.group("body"))
        effects = parse_effect_body(body, reading=ClauseReading(self_subject=True))
        if effects is None:
            return Segment(raw=raw)
        for e in effects:
            e.condition = {**(e.condition or {}), "source_was_cast": True}
            # "…for a creature card with mana value X or less…" (Rocco,
            # Cabaretti Caterer) — this whole row is *always* a triggered
            # ability firing after its own casting resolution ended, so the
            # generic bare ``"x"`` sentinel (tied to the *current* stack
            # item's announced X, which is 0 for a trigger) is always wrong
            # here; rewrite to `GameObject.x_paid`'s own ``"source_x_paid"``
            # sentinel (Invasion of Ikoria's existing idiom) instead.
            for key, value in list(e.params.items()):
                if value == "x":
                    e.params[key] = "source_x_paid"
                elif isinstance(value, dict):
                    for inner_key, inner_value in list(value.items()):
                        if inner_value == "x":
                            value[inner_key] = "source_x_paid"
        spec = AbilitySpec(
            "triggered",
            effects=effects,
            trigger={"event": "ENTERS_BATTLEFIELD", "condition": {"subject": "self"}},
            optional=optional,
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def line_enters_if_madness(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    enters_if_madness = ENTERS_IF_MADNESS_PAID_RE.match(raw)
    if enters_if_madness is not None:
        body, optional = peel_optional(enters_if_madness.group("body"))
        effects = parse_effect_body(body, reading=ClauseReading(self_subject=True))
        if effects is None:
            return Segment(raw=raw)
        for e in effects:
            e.condition = {
                **(e.condition or {}), f"{enters_if_madness.group('cost').lower()}_cost_paid": True,
            }
        spec = AbilitySpec(
            "triggered",
            effects=effects,
            trigger={"event": "ENTERS_BATTLEFIELD", "condition": {"subject": "self"}},
            optional=optional,
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def line_cast_spell_not_their_turn_trig(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    cast_spell_not_their_turn_trig = CAST_SPELL_NOT_THEIR_TURN_TRIGGER_RE.match(raw)
    if cast_spell_not_their_turn_trig is not None:
        body, optional = peel_optional(cast_spell_not_their_turn_trig.group("body"))
        effects = parse_effect_body(body)
        if effects is None:
            return Segment(raw=raw)
        spec = AbilitySpec(
            "triggered",
            effects=effects,
            trigger={
                "event": "SPELL_CAST",
                "condition": {"subject": "group"},
                "not_controllers_turn": True,
            },
            optional=optional,
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def line_cast_spell_no_mana_trig(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    cast_spell_no_mana_trig = CAST_SPELL_NO_MANA_TRIGGER_RE.match(raw)
    if cast_spell_no_mana_trig is not None:
        body, optional = peel_optional(cast_spell_no_mana_trig.group("body"))
        effects = parse_effect_body(body)
        if effects is None:
            return Segment(raw=raw)
        spec = AbilitySpec(
            "triggered",
            effects=effects,
            trigger={
                "event": "SPELL_CAST",
                "condition": {"subject": "group"},
                "spell_no_mana_spent": True,
            },
            optional=optional,
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def line_cast_spell_targets_src(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    cast_spell_targets_src = CAST_SPELL_TARGETS_SOURCE_TRIGGER_RE.match(raw)
    if cast_spell_targets_src is not None:
        body, optional = peel_optional(cast_spell_targets_src.group("body"))
        effects = parse_effect_body(body, reading=ClauseReading(self_subject=True))
        if effects is None:
            return Segment(raw=raw)
        spec = AbilitySpec(
            "triggered",
            effects=effects,
            trigger={
                "event": "SPELL_CAST",
                "condition": cast_spell_trigger_condition("you"),
                "requires_spell_targets_source": True,
            },
            optional=optional,
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def line_cast_spell_shares_type(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    cast_spell_shares_type = CAST_SPELL_SHARES_TYPE_SOURCE_TRIGGER_RE.match(raw)
    if cast_spell_shares_type is not None:
        body, optional = peel_optional(cast_spell_shares_type.group("body"))
        effects = parse_effect_body(body, reading=ClauseReading(self_subject=True))
        if effects is None:
            return Segment(raw=raw)
        effects, body_limit = strip_trigger_once_per_turn_marker(effects)
        spec = AbilitySpec(
            "triggered",
            effects=effects,
            trigger={
                "event": "SPELL_CAST",
                "condition": cast_spell_trigger_condition("you"),
                "spell_shares_creature_type_with_source": True,
                **({"limit": True} if body_limit else {}),
            },
            optional=optional,
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def line_cast_spell_targets_perm(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    cast_spell_targets_perm = CAST_SPELL_TARGETS_PERMANENT_TRIGGER_RE.match(raw)
    if cast_spell_targets_perm is not None:
        subj = cast_spell_targets_perm.group("subj").lower()
        body, optional = peel_optional(cast_spell_targets_perm.group("body"))
        effects = parse_effect_body(body)
        if effects is None:
            return Segment(raw=raw)
        spec = AbilitySpec(
            "triggered",
            effects=effects,
            trigger={
                "event": "SPELL_CAST",
                "condition": cast_spell_trigger_condition(subj),
                "requires_spell_targets_permanent": True,
            },
            optional=optional,
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def line_two_color_cast(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    two_color_cast = CAST_TWO_COLOR_SPELL_TRIGGER_RE.match(raw)
    if two_color_cast is not None:
        body, optional = peel_optional(two_color_cast.group("body"))
        effects = parse_effect_body(body, reading=ClauseReading(self_subject=True))
        mimic_body = re.fullmatch(
            r"~ has base power and toughness (?P<p>\d+)/(?P<t>\d+) until end of turn and "
            r"(?P<tail>gains? [a-z ]+|can'?t be blocked this turn)\.", body.strip(), re.I,
        )
        if effects is None and mimic_body is not None:
            effects = [EffectSpec("grant_until", {
                "static": {"type": "pt_set", "params": {
                    "power": int(mimic_body.group("p")), "toughness": int(mimic_body.group("t")),
                }}, "duration": "end_of_turn", "target_kind": None,
            })]
            tail = mimic_body.group("tail").lower()
            if tail.startswith("gains "):
                effects.append(EffectSpec("pump", {"keywords": [tail.removeprefix("gains ")]}))
            else:
                effects.append(EffectSpec("pump", {"unblockable": True}))
        if effects is None:
            return Segment(raw=raw)
        colors = [
            CAST_SPELL_COLOR_WORDS[two_color_cast.group("c1").lower()],
            CAST_SPELL_COLOR_WORDS[two_color_cast.group("c2").lower()],
        ]
        spec = AbilitySpec("triggered", effects=effects, trigger={
            "event": "SPELL_CAST",
            "condition": cast_spell_trigger_condition(two_color_cast.group("subj")),
            "cast_of_all_colors": colors,
        }, optional=optional, raw_text=raw, parser=provenance)
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def line_cast_this_spell_trig(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    cast_this_spell_trig = CAST_THIS_SPELL_TRIGGER_RE.match(raw)
    if cast_this_spell_trig is not None:
        body, optional = peel_optional(cast_this_spell_trig.group("body"))
        # RULE 603.2 / 707.10: the casting event identifies this spell;
        # copying it neither casts it nor creates another cast trigger.
        effects = ([EffectSpec("copy_spell", {"spell_from_trigger_event": "instance_id"})]
                   if body.strip().rstrip(".") in ("copy it", "copy this spell")
                   else parse_effect_body(body, reading=ClauseReading(self_subject=True)))
        if effects is None:
            return Segment(raw=raw)
        spec = AbilitySpec(
            "triggered",
            effects=effects,
            trigger={"event": "SPELL_CAST", "condition": {"subject": "self"}},
            optional=optional,
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def line_draw_trig_plain(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    draw_trig_plain = DRAW_TRIGGER_PLAIN_RE.match(raw)
    if draw_trig_plain is not None:
        subj = draw_trig_plain.group("subj").lower()
        body, optional = peel_optional(draw_trig_plain.group("body"))
        effects = parse_effect_body(body)
        if effects is None:
            return Segment(raw=raw)
        spec = AbilitySpec(
            "triggered",
            effects=effects,
            trigger={"event": "DRAW", "condition": cast_spell_trigger_condition(subj)},
            optional=optional,
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def line_reveal_first(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    reveal_first = REVEAL_FIRST_DRAW_RE.match(raw)
    if reveal_first is not None:
        body, optional = peel_optional(reveal_first.group("body"))
        effects = parse_effect_body(body)
        if effects is None or any(effect.condition for effect in effects):
            return Segment(raw=raw)
        gate: dict[str, Any] = {"kind": "is_card_type", "of": "first_drawn_this_turn",
                                "card_type": reveal_first.group("type").lower()}
        if reveal_first.group("basic"):
            gate = {"kind": "all", "conditions": [
                gate, {"kind": "is_basic", "of": "first_drawn_this_turn"}]}
        spec = AbilitySpec(
            "triggered",
            effects=[EffectSpec(e.type, e.params, condition=gate) for e in effects],
            trigger={"event": "DRAW", "condition": cast_spell_trigger_condition("you"),
                     "is_nth_draw_this_turn": 1},
            optional=optional,
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def line_draw_trig_nth(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    draw_trig_nth = DRAW_CARD_TRIGGER_NTH_RE.match(raw)
    if draw_trig_nth is not None:
        subj = draw_trig_nth.group("subj").lower()
        n = CAST_SPELL_ORDINAL_WORDS[draw_trig_nth.group("ordinal").lower()]
        body, optional = peel_optional(draw_trig_nth.group("body"))
        effects = parse_effect_body(body)
        if effects is None:
            return Segment(raw=raw)
        spec = AbilitySpec(
            "triggered",
            effects=effects,
            trigger={
                "event": "DRAW",
                "condition": cast_spell_trigger_condition(subj),
                "is_nth_draw_this_turn": n,
            },
            optional=optional,
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def line_tap_mana_trig(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    tap_mana_trig = TAP_FOR_MANA_TRIGGER_RE.match(raw)
    if tap_mana_trig is not None:
        subj = tap_mana_trig.group("subj").lower()
        land = tap_mana_trig.group("land").lower()
        body, optional = peel_optional(tap_mana_trig.group("body"))
        effects = parse_effect_body(body)
        if effects is None:
            return Segment(raw=raw)
        condition: dict[str, Any] = {"subject": "group", "type": "land"}
        if land != "land":
            condition["subtypes"] = [land]
        if subj == "you":
            condition["controller"] = "you"
        spec = AbilitySpec(
            "triggered",
            effects=effects,
            trigger={"event": "TAPPED_FOR_MANA", "condition": condition, "mana_ability": True},
            optional=optional,
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def line_doctor_or_companion_trig(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    doctor_or_companion_trig = DOCTOR_OR_COMPANION_CREATURE_CAST_TRIGGER_RE.match(raw)
    if doctor_or_companion_trig is not None:
        body, optional = peel_optional(doctor_or_companion_trig.group("body"))
        effects = parse_effect_body(body, reading=ClauseReading(self_subject=True))
        if effects is None:
            return Segment(raw=raw)
        doctor_spec = AbilitySpec(
            "triggered",
            effects=effects,
            trigger={
                "event": "SPELL_CAST",
                "condition": {"subject": "you"},
                "spell_subtype_any": ["doctor"],
            },
            optional=optional,
            raw_text=raw,
            parser=provenance,
        )
        companion_spec = AbilitySpec(
            "triggered",
            effects=effects,
            trigger={
                "event": "SPELL_CAST",
                "condition": {"subject": "you"},
                "spell_card_types": ["creature"],
                "spell_has_keyword": "Doctor's Companion",
            },
            optional=optional,
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=doctor_spec, extra_specs=[companion_spec], claimed=True)
    return None


#: PAR-236, RULE 707.10: "...casts a spell other than the first spell they cast each turn **or copies a spell**" (Curse of
#: Shaken Faith) -- the ordinal limits only the cast; a copy (`SPELL_COPIED`, never "cast") triggers on its own.
_AND_COPIES_A_SPELL_RE = re.compile(r"^(?P<cast>.+?) or copies a spell$")


def _cast_or_copy_segment(
    raw: str, composed_cast: "re.Match[str]", cast_phrase: str, provenance: ParserProvenance
) -> Optional[Segment]:
    keys = parse_spell_phrase(cast_phrase)
    if keys is None:
        return None
    subj, body = composed_cast.group("subj"), composed_cast.group("body")
    cast = cast_trigger_segment(raw, subj, keys, body, provenance)
    copy = cast_trigger_segment(raw, subj, {"event": "SPELL_COPIED"}, body, provenance)
    if not (cast.claimed and cast.spec is not None and copy.claimed and copy.spec is not None):
        return None
    return Segment(raw=raw, spec=cast.spec, extra_specs=[*cast.extra_specs, copy.spec, *copy.extra_specs], claimed=True)


def line_composed_cast(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    composed_cast = CAST_TRIGGER_COMPOSED_RE.match(raw)
    if composed_cast is not None:
        also_copies = _AND_COPIES_A_SPELL_RE.match(composed_cast.group("phrase"))
        if also_copies is not None and not composed_cast.group("copies"):
            return _cast_or_copy_segment(raw, composed_cast, also_copies.group("cast"), provenance)
        composed_keys = parse_spell_phrase(composed_cast.group("phrase"))
        if composed_keys is not None:
            if composed_cast.group("copies"):
                composed_keys["event"] = ["SPELL_CAST", "SPELL_COPIED"]
            return cast_trigger_segment(
                raw, composed_cast.group("subj"), composed_keys, composed_cast.group("body"), provenance
            )
    return None


def line_cycle_trig(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    cycle_trig = CYCLE_TRIGGER_RE.match(raw)
    if cycle_trig is not None:
        body = cycle_trig.group("body")
        # RULE 702.28c's X (Shark Typhoon's "create an X/X ... token"): the
        # Cycling cost's own paid {X}, ambiguous to any *generic* "create an
        # X/X ... token" handler outside this wrapper (see `_cycling_xx_
        # token`'s own docstring) — checked directly, here, rather than
        # through the ordinary HANDLERS table this body would otherwise go
        # through via `parse_effect_body`.
        xx_token_match = CYCLING_XX_TOKEN_RE.fullmatch(body.strip().rstrip(".").strip())
        if xx_token_match is not None:
            effects = cycling_xx_token(xx_token_match)
        else:
            effects = parse_effect_body(body, reading=ClauseReading(self_subject=True))
        if effects is None:
            return Segment(raw=raw)
        spec = AbilitySpec(
            "triggered",
            effects=effects,
            trigger={"event": "CYCLED", "condition": {"subject": "self"}},
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def line_caused_discard_replacement(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    if CAUSED_DISCARD_REPLACEMENT_RE.match(raw) is not None:
        return Segment(raw=raw, claimed=True, spec=AbilitySpec(
            "replacement", [EffectSpec("discard_to_battlefield", {})],
            raw_text=raw, parser=provenance,
        ))
    return None


def line_caused_discard(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    caused_discard = OPPONENT_CAUSED_DISCARD_TRIGGER_RE.match(raw)
    if caused_discard is not None:
        is_self = caused_discard.group("what").lower() != "a card"
        effects = caused_discard_effects(caused_discard.group("body"), is_self)
        if effects is None:
            return Segment(raw=raw)
        spec = AbilitySpec(
            "triggered",
            effects=effects,
            trigger={
                "event": "DISCARD_CARD",
                "condition": {"subject": "self" if is_self else "you"},
                "requires_opponent_caused_discard": True,
            },
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def line_self_discard(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    self_discard = SELF_DISCARD_TRIGGER_RE.match(raw)
    if self_discard is None:
        return None
    effects = parse_effect_body(self_discard.group("body"), reading=ClauseReading(self_subject=True))
    if effects is None:
        return Segment(raw=raw)
    spec = AbilitySpec(
        "triggered",
        effects=effects,
        trigger={"event": "DISCARD_CARD", "condition": {"subject": "self"}},
        raw_text=raw,
        parser=ctx.provenance,
    )
    return Segment(raw=raw, spec=spec, claimed=True)


def line_exert_bare(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    if EXERT_BARE_RE.match(raw) is not None:
        return Segment(raw=raw, claimed=True, keyword_line=True)
    return None


def line_exert_trig(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    exert_trig = EXERT_TRIGGER_RE.match(raw)
    if exert_trig is not None:
        # "…as he attacks. When you do, he gains flying" (Themberchaud): the effect grammar
        # knows the self-pronoun as "it".
        body = re.sub(r"\b(?:he|she)\b", "it", exert_trig.group("body"))
        effects = parse_effect_body(body, reading=ClauseReading(self_subject=True))
        if effects is None:
            return Segment(raw=raw)
        spec = AbilitySpec(
            "triggered",
            effects=effects,
            trigger={"event": "EXERTED", "condition": {"subject": "self"}},
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def line_exert_player_trig(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    exert_player_trig = EXERT_PLAYER_TRIGGER_RE.match(raw)
    if exert_player_trig is not None:
        effects = parse_effect_body(exert_player_trig.group("body"))
        if effects is None:
            return Segment(raw=raw)
        spec = AbilitySpec(
            "triggered",
            effects=effects,
            trigger={"event": "EXERTED", "condition": {"subject": "you"}},
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def line_sacrifice_trig(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    sacrifice_trig = SACRIFICE_TYPE_TRIGGER_RE.match(raw)
    if sacrifice_trig is not None:
        effects = parse_effect_body(sacrifice_trig.group("body"), reading=ClauseReading(self_subject=True))
        if effects is None:
            return Segment(raw=raw)
        spec = AbilitySpec(
            "triggered",
            effects=effects,
            trigger={
                "event": "SACRIFICE",
                "condition": {"subject": "you"},
                "sacrifice_type": [
                    t.lower() for t in (sacrifice_trig.group("type"), sacrifice_trig.group("type2")) if t
                ],
            },
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def line_control_none_matching(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    control_none_matching = CONTROL_NONE_MATCHING_RE.match(raw)
    if control_none_matching is not None:
        effects = parse_effect_body(control_none_matching.group("body"), reading=ClauseReading(self_subject=True))
        if effects is None:
            return Segment(raw=raw)
        quality: dict[str, Any] = {"subtype": control_none_matching.group("sub").lower()}
        if control_none_matching.group("leg"):
            quality["legendary"] = True
        return Segment(raw=raw, spec=AbilitySpec(
            "triggered", effects=effects,
            trigger={"event": "STATE_CHECK", "controls_none_matching": quality},
            raw_text=raw, parser=provenance,
        ), claimed=True)
    return None


def line_control_none_sac(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    control_none_sac = CONTROL_NONE_SACRIFICE_RE.match(raw)
    if control_none_sac is not None:
        effects = parse_effect_body(control_none_sac.group("body"), reading=ClauseReading(self_subject=True))
        if effects is None:
            return Segment(raw=raw)
        land_type = BASIC_LAND_TYPE_SINGULAR[control_none_sac.group("type").lower()]
        spec = AbilitySpec(
            "triggered",
            effects=effects,
            trigger={
                "event": "LEAVES_BATTLEFIELD",
                "controls_none_of_type": land_type,
            },
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None
