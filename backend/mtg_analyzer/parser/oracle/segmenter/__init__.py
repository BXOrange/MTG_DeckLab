"""Step 2 of the front-end pipeline: segment abilities (docs/09).

Reference: docs/concepts/09_ORACLE_EFFECT_PARSER.md ("THE FRONT-END PIPELINE", step 2
SEGMENT). Splits *normalised* card text into individual abilities and peels
the wrapper off each one — the trigger phrase of a triggered ability, the
"you may" optionality — leaving a bare **effect body** for the handler table
(step 3) to claim. Keyword lines are recognised so the coverage gate can
account for them (their actual specs come from the keyword catalogue, which
anchors on Scryfall's `keywords` array).

Pure text/data — **no `game/` imports** (front-end security boundary). The
`EventType` strings a trigger maps to are hard-coded here with a comment and
kept in sync with `models/events.py` by `tests/test_oracle_segmenter.py`,
so the front-end stays import-pure.

Layout (ENG-59, the PAR-172 split method): this package is the entry point (`LINE_MATCHERS`, `segment_line_unsplit`,
re-exports); the sibling modules are the former single file in dependency order: `trigger_heads` (trigger vocabulary),
`activation_clauses`, `condition_riders`, `cost_line_patterns`, `keyword_and_trigger_conditions`, `referents`,
`pronoun_stamping`, `conditions`, `overrides_and_amounts`, `where_x`, `effect_body`, `keyword_lines`, `segment_forms`,
and the `LINE_MATCHERS` rows in `line_rows_*`. The effect-body parser and the line segmenter are mutually recursive, so
a module earlier in that order reaches the few later entry points through the forwarders in `late` (registered by the
defining module at import).
"""
from __future__ import annotations

from ..catalogue.clause_hooks import register_segmenter
from ..catalogue.handlers import match_clause
from ..catalogue.static_handlers import static_condition
from ..spec import ParserProvenance
from .segment_types import Segment
from .effect_body import parse_effect_body
from .segment_forms import segment_line
from .line_types import LineContext, LineMatcher
from .line_rows_triggers import (
    line_attack_meld,
    line_cast_spell_no_mana_trig,
    line_cast_spell_not_their_turn_trig,
    line_cast_spell_shares_type,
    line_cast_spell_targets_perm,
    line_cast_spell_targets_src,
    line_cast_this_spell_trig,
    line_caused_discard,
    line_self_discard,
    line_caused_discard_replacement,
    line_composed_cast,
    line_control_none_matching,
    line_control_none_sac,
    line_counter_free_spell,
    line_cycle_trig,
    line_doctor_or_companion_trig,
    line_draw_trig_nth,
    line_draw_trig_plain,
    line_enters_if_cast,
    line_enters_if_madness,
    line_equip_dash,
    line_equip_once_each_turn,
    line_etb_and_cast,
    line_exert_bare,
    line_exert_player_trig,
    line_exert_trig,
    line_kw_labeled,
    line_magecraft,
    line_meld_trig,
    line_neither_day_nor_night,
    line_play_with_top_revealed,
    line_reveal_first,
    line_sacrifice_trig,
    line_split_heads,
    line_tap_mana_trig,
    line_two_color_cast,
    line_wordy,
)
from .line_rows_cast_only import line_cast_only_window_or_condition
from .line_rows_costs import (
    line_additional_cost_line,
    line_alt_cost_discard_land,
    line_alt_cost_exile_hand_color,
    line_alt_cost_exile_hand_color_count,
    line_alt_cost_exile_hand_if_not_your_turn,
    line_alt_cost_pay_life_and_exile_hand,
    line_alt_cost_pay_life_if_control_land,
    line_alt_cost_pay_mana,
    line_alt_cost_pay_mana_and_return_land,
    line_alt_cost_pay_mana_if_attacking,
    line_alt_cost_pay_mana_if_condition,
    line_alt_cost_sacrifice_if_your_turn,
    line_alt_cost_pay_mana_if_treasure,
    line_alt_cost_pay_mana_if_you_attacked,
    line_alt_cost_return_two,
    line_alt_cost_sacrifice_count,
    line_alt_cost_sacrifice_filter,
    line_alt_cost_sacrifice_if_control_land,
    line_alt_cost_sacrifice_type,
    line_alt_cost_tap_creature_if_control_land,
    line_before_blockers_cast_only,
    line_cast_mana_source_restriction,
    line_cast_only_if_another_color,
    line_collect_evidence_discount,
    line_combat_cast_only,
    line_conditional_flash_board_state,
    line_conditional_flash_for_mana,
    line_declare_attackers_if_attacked,
    line_flash_then_cleanup_sac,
    line_spell_free_cast_conditions,
)
from .line_rows_abilities import (
    line_activated_ability,
    line_loyalty_ability,
    line_permanent_standing_line,
    line_phase_trigger,
    line_saga_chapter,
    line_spell_cost_static,
    line_spell_effect_imperative,
    line_triggered_ability,
)
from .defending_player_trigger import line_defending_player_trigger
from .keyword_and_trigger_conditions import trigger_condition_dict
from .late import register
from .optional_peel import peel_optional  # noqa: F401
from .trigger_heads import TRIGGER_RE  # noqa: F401
from .referents import produces  # noqa: F401
from .keyword_lines import is_keyword_line  # noqa: F401
from .segment_forms import FLASHBACK_DISCOUNT_LINE_RE  # noqa: F401


LINE_MATCHERS: tuple[LineMatcher, ...] = (
    LineMatcher("neither_day_nor_night", line_neither_day_nor_night),
    LineMatcher("kw_labeled", line_kw_labeled),
    LineMatcher("equip_dash", line_equip_dash),
    LineMatcher("equip_once_each_turn", line_equip_once_each_turn),
    LineMatcher("etb_and_cast", line_etb_and_cast),
    LineMatcher("split_heads", line_split_heads),
    LineMatcher("play_with_top_revealed", line_play_with_top_revealed),
    LineMatcher("meld_trig", line_meld_trig),
    LineMatcher("attack_meld", line_attack_meld),
    LineMatcher("wordy", line_wordy),
    LineMatcher("magecraft", line_magecraft),
    LineMatcher("counter_free_spell", line_counter_free_spell),
    LineMatcher("enters_if_cast", line_enters_if_cast),
    LineMatcher("enters_if_madness", line_enters_if_madness),
    LineMatcher("cast_spell_not_their_turn_trig", line_cast_spell_not_their_turn_trig),
    LineMatcher("cast_spell_no_mana_trig", line_cast_spell_no_mana_trig),
    LineMatcher("cast_spell_targets_src", line_cast_spell_targets_src),
    LineMatcher("cast_spell_shares_type", line_cast_spell_shares_type),
    LineMatcher("cast_spell_targets_perm", line_cast_spell_targets_perm),
    LineMatcher("two_color_cast", line_two_color_cast),
    LineMatcher("cast_this_spell_trig", line_cast_this_spell_trig),
    LineMatcher("draw_trig_plain", line_draw_trig_plain),
    LineMatcher("reveal_first", line_reveal_first),
    LineMatcher("draw_trig_nth", line_draw_trig_nth),
    LineMatcher("tap_mana_trig", line_tap_mana_trig),
    LineMatcher("doctor_or_companion_trig", line_doctor_or_companion_trig),
    LineMatcher("composed_cast", line_composed_cast),
    LineMatcher("cycle_trig", line_cycle_trig),
    LineMatcher("caused_discard_replacement", line_caused_discard_replacement),
    LineMatcher("caused_discard", line_caused_discard),
    LineMatcher("self_discard", line_self_discard),
    LineMatcher("exert_bare", line_exert_bare),
    LineMatcher("exert_trig", line_exert_trig),
    LineMatcher("exert_player_trig", line_exert_player_trig),
    LineMatcher("sacrifice_trig", line_sacrifice_trig),
    LineMatcher("control_none_matching", line_control_none_matching),
    LineMatcher("control_none_sac", line_control_none_sac),
    LineMatcher("alt_cost_exile_hand_color", line_alt_cost_exile_hand_color),
    LineMatcher("alt_cost_sacrifice_filter", line_alt_cost_sacrifice_filter),
    LineMatcher("alt_cost_sacrifice_type", line_alt_cost_sacrifice_type),
    LineMatcher("alt_cost_return_two", line_alt_cost_return_two),
    LineMatcher("alt_cost_pay_life_if_control_land", line_alt_cost_pay_life_if_control_land),
    LineMatcher("alt_cost_pay_mana_if_attacking", line_alt_cost_pay_mana_if_attacking),
    LineMatcher("alt_cost_sacrifice_if_your_turn", line_alt_cost_sacrifice_if_your_turn),
    LineMatcher("alt_cost_pay_mana_if_you_attacked", line_alt_cost_pay_mana_if_you_attacked),
    LineMatcher("alt_cost_pay_mana_if_condition", line_alt_cost_pay_mana_if_condition),
    LineMatcher("alt_cost_pay_mana", line_alt_cost_pay_mana),
    LineMatcher("alt_cost_sacrifice_if_control_land", line_alt_cost_sacrifice_if_control_land),
    LineMatcher("alt_cost_tap_creature_if_control_land", line_alt_cost_tap_creature_if_control_land),
    LineMatcher("alt_cost_pay_mana_and_return_land", line_alt_cost_pay_mana_and_return_land),
    LineMatcher("alt_cost_sacrifice_count", line_alt_cost_sacrifice_count),
    LineMatcher("alt_cost_exile_hand_color_count", line_alt_cost_exile_hand_color_count),
    LineMatcher("alt_cost_exile_hand_if_not_your_turn", line_alt_cost_exile_hand_if_not_your_turn),
    LineMatcher("alt_cost_pay_life_and_exile_hand", line_alt_cost_pay_life_and_exile_hand),
    LineMatcher("alt_cost_discard_land", line_alt_cost_discard_land),
    LineMatcher("alt_cost_pay_mana_if_treasure", line_alt_cost_pay_mana_if_treasure),
    LineMatcher("cast_mana_source_restriction", line_cast_mana_source_restriction),
    LineMatcher("collect_evidence_discount", line_collect_evidence_discount),
    LineMatcher("additional_cost_line", line_additional_cost_line),
    LineMatcher("declare_attackers_if_attacked", line_declare_attackers_if_attacked),
    LineMatcher("combat_cast_only", line_combat_cast_only),
    LineMatcher("before_blockers_cast_only", line_before_blockers_cast_only),
    LineMatcher("cast_only_if_another_color", line_cast_only_if_another_color),
    LineMatcher("cast_only_window_or_condition", line_cast_only_window_or_condition),
    LineMatcher("conditional_flash_for_mana", line_conditional_flash_for_mana),
    LineMatcher("flash_then_cleanup_sac", line_flash_then_cleanup_sac),
    LineMatcher("conditional_flash_board_state", line_conditional_flash_board_state),
    LineMatcher("spell_free_cast_conditions", line_spell_free_cast_conditions),
    LineMatcher("saga_chapter", line_saga_chapter),
    LineMatcher("loyalty_ability", line_loyalty_ability),
    LineMatcher("activated_ability", line_activated_ability),
    LineMatcher("phase_trigger", line_phase_trigger),
    LineMatcher("defending_player_trigger", line_defending_player_trigger),
    LineMatcher("triggered_ability", line_triggered_ability),
    LineMatcher("permanent_standing_line", line_permanent_standing_line),
    LineMatcher("spell_cost_static", line_spell_cost_static),
    LineMatcher("spell_effect_imperative", line_spell_effect_imperative),
)


def segment_line_unsplit(
    line: str,
    *,
    allow_spell_effect: bool,
    provenance: ParserProvenance,
    is_saga: bool = False,
) -> Segment:
    """Parse one normalised ability ``line`` into a `Segment`.

    ``allow_spell_effect`` gates bare imperative clauses (no trigger wrapper)
    to instants/sorceries — a permanent's non-triggered imperative would be
    mis-modeled as a resolve-time effect, so for permanents it's left unclaimed
    (fail-closed) rather than turned into a `spell_effect`. ``is_saga`` gates
    the RULE 715 chapter-line grammar ("i, ii — <effect>") to actual Sagas, so
    the numeral-dash shape can't misfire on an unrelated card.
    """
    raw = line.strip()
    if not raw:
        return Segment(raw=raw, claimed=True)  # blank lines are trivially covered
    ctx = LineContext(
        raw=raw, line=line, allow_spell_effect=allow_spell_effect, provenance=provenance, is_saga=is_saga
    )
    for matcher in LINE_MATCHERS:
        segment = matcher.match(ctx)
        if segment is not None:
            return segment
    return Segment(raw=raw)  # unreachable: the last matcher always returns; unclaimed is the fail-closed fallback


# The handlers, static handlers and sequence grammars recurse into these entry points through
# `catalogue.clause_hooks` (PAR-172: the one real cycle, broken by late binding, not by imports).
register_segmenter(
    parse_effect_body=parse_effect_body,
    segment_line=segment_line,
    trigger_condition_dict=trigger_condition_dict,
)


# Late-bound entry points other modules of this package call before this one is defined (see `late`).
register(segment_line_unsplit=segment_line_unsplit)
