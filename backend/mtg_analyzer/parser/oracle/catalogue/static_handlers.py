"""Static continuous-ability handlers — anthems and keyword grants (docs/09).

Reference: docs/concepts/09_ORACLE_EFFECT_PARSER.md (effect-family handlers), RULE 613
(the layer system these feed). A *permanent's* standing sentence like "Other
creatures you control get +1/+1" or "Goblins you control have haste" is a
**static** ability, not a one-shot effect — it reshapes other permanents
continuously while its source is in play. This module recognises those two
families and emits `EffectSpec`s the binder turns into `StaticAbility`s
(`anthem` → layer 7c, `grant_keyword` → layer 6), with a tribal **subtype**
filter for lords (Goblin King, Lord of Atlantis).

Only creature scopes are claimed — "creatures you control", a plural creature
type ("goblins you control"), or "<type> creatures you control" — with a small
block-list keeping non-creature scopes ("artifacts you control …") from being
mis-read as anthems (fail-closed). Anything with an "until end of turn" tail is
a *temporary* effect an instant grants, not a static ability, and won't
full-match here.

A second, closed family recognises an Aura/Equipment/Fortification's own
attached-permanent buff — "equipped creature gets +2/+2", "enchanted creature
has trample" (RULE 303.4/301.5, docs/11 §6 "attached_permanent"). Unlike the
"you control" scopes above, these five printed subject phrases
(`_ATTACHED_SUBJECTS`) always resolve off the ability's own source's
`attached_to`, so they emit `affects="attached_permanent"` rather than any
controller-scoped selector; `game/continuous.py`'s `group_selector_objects`
already honours that selector for both `anthem` and `grant_keyword` (it's the
same code path the hand-authored Armadillo Cloak entry in
`game/card_catalogue` uses) — only the parser recognition was missing.

A third family (Card-pool Batch 7) recognises RULE 601.2b's "as ~ enters,
choose a creature type/color" (`enter_choice_specs`, a sibling entry point
segmenter.py calls separately since it wraps as an ``enter_replacement``
`AbilitySpec`, not ``static``) plus the "… of the chosen type/color …"
dynamic tail on the anthem/grant families above (`_CHOSEN_TAIL`) and "~ is
the chosen type in addition to its other types" (`_IS_CHOSEN_TYPE_RE`) — see
`game/continuous.py`'s ``subtype_from_source``/``color_from_source``/
``add_subtypes_from_source`` params for how the layer engine reads the
choice back.

A fourth family (Card-pool Batch 8) recognises three "permission" statics
that aren't about a permanent's own characteristics at all: "you may play an
additional land on each of your turns" (`extra_land_drop`), "you have no
maximum hand size" (`no_max_hand_size`), and "you may choose not to untap ~
during your untap step" (`no_untap_optional`) — all consulted by
per-*player*/per-*object* helpers in `game/continuous.py` rather than the
RULE 613 layer engine proper (the same treatment `cast_limit`/`draw_limit`/
`no_untap` already got).

Layout (ENG-59, the PAR-172 split method): the regex tables, helpers and per-row matchers live in `static_rows/`
(dependency order: `anthem_patterns`, `object_scope`, `combat_restrictions`, `keyword_flags`, `cost_patterns`,
`granted_abilities`, `static_conditions`, `enter_choices`, `self_statics`, `matcher_types`, then the `rows_*` modules);
this module assembles the ordered `STATIC_MATCHERS` table, owns `static_effect_specs` and re-exports the public names.

Pure regex + data — **no `game/` imports** (front-end security boundary).
"""
from __future__ import annotations

from dataclasses import replace
from typing import Optional, Union
from ..spec import EffectSpec
from .clause_hooks import register_static_condition, register_static_effect_specs
from .static_rows.static_conditions import static_condition
from .static_rows.matcher_types import DECLINE, StaticContext, StaticMatcher, StaticRewrite
from .static_rows.rows_self_and_cost import (
    static_blitz_cost_reduction,
    static_blitz_graveyard_permission,
    static_cant_be_countered_self,
    static_cast_timing_flash_and_restriction,
    static_colored_quoted_self,
    static_commander_damage_triple,
    static_compound_self,
    static_conditional_otherwise,
    static_conditional_static_specs,
    static_damage_as_unblocked,
    static_during_other_turns_cost,
    static_enters_with_counters_count,
    static_extra_etb_counter_specs,
    static_fixed_base,
    static_flag_keywords,
    static_flash_permission,
    static_fold_additional,
    static_grant_cant_be_countered,
    static_grant_search_prohibited,
    static_grant_skip_extra_turns,
    static_lands_every_basic_type,
    static_match,
    static_match_2,
    static_pip_life_option,
    static_pt_cda,
    static_pt_cda_single,
    static_pt_cda_that_number,
    static_quoted_self,
    static_quoted_tail,
    static_self_graveyard_shuffle,
    static_storm_grant,
    static_toughness_damage,
    static_trigger_doubler,
    static_turn_split_fixed_pt,
    static_turn_split_pt,
)
from .static_rows.rows_group_subjects import (
    static_each_creature_thats,
    static_each_permanent_gets_if_creature,
    static_legendary_permanents_grant,
)
from .static_rows.rows_typed_groups import static_typed_group_statement
from .static_rows.rows_attached_transform import (
    static_attached_creature_types,
    static_attached_land_basic_type,
    static_attached_loses_abilities_transform,
    static_attached_permanent_is,
    static_self_type_addition,
)
from .static_rows.rows_cost_tax import (
    static_ability_cost_modifier,
    static_activation_cost_reduction_type,
    static_activation_prohibition,
    static_activation_prohibition_opponents,
    static_additional_activation_cost,
    static_cant_cast_opponents_hand_only,
    static_cant_cast_defending_player,
    static_cant_cast_opponents_your_turn,
    static_cant_cast_or_activate_opponents,
    static_cast_limit,
    static_cast_limit_noncreature,
    static_equip_activation_discount,
    static_equip_self_discount,
    static_extra_land_drop,
    static_keyword_cost_modifier,
    static_named_card,
    static_second_spell_cost_reduction,
    static_self_cost_reduction_colored,
    static_self_cost_reduction_for_each,
    static_self_cost_reduction_if,
    static_self_cost_reduction_where_x,
    static_spell_cost_tax,
    static_spell_cost_tax_color,
    static_spell_cost_tax_commander,
    static_spell_cost_tax_opponents,
    static_spell_cost_tax_that_target,
    static_spell_cost_tax_you_cast,
)
from .static_rows.rows_attached import (
    static_anthem_devotion_self,
    static_attached_anthem,
    static_attached_anthem_for_each,
    static_attached_anthem_protection,
    static_attached_anthem_x,
    static_attached_goaded,
    static_attached_grant,
    static_attached_protection,
    static_attached_remove_keyword,
    static_attached_trailing_type,
    static_attached_type_addition,
    static_group_anthem_protection,
    static_group_protection,
    static_self_anthem,
    static_self_anthem_for_each,
    static_self_anthem_for_each_gy_subtype,
    static_self_grant,
    static_self_protection,
)
from .static_rows.rows_player_rules import (
    static_activate_as_though_haste,
    static_all_enter_tapped,
    static_attached_ability_loss,
    static_color_statement_specs,
    static_damage_cant_be_prevented,
    static_graveyard_cast,
    static_graveyard_land_play_permission,
    static_graveyard_library_cast_prohibition,
    static_graveyard_library_entry_prohibition,
    static_hand_size_modifier,
    static_ignore_legend_rule,
    static_land_is_basic_type,
    static_all_basic_type_becomes,
    static_linked_exile_permission,
    static_look_at_top_any_time,
    static_cant_lose_for_life,
    static_no_max_hand_size,
    static_no_untap,
    static_no_untap_attached,
    static_no_untap_group_power,
    static_no_untap_nonbasic_lands,
    static_no_untap_optional,
    static_not_a_creature,
    static_opponents_enter_tapped,
    static_players_cant_draw,
    static_players_cant_gain_life,
    static_radiation_life_gain,
    static_skip_untap_steps,
    static_skip_your_step,
    static_top_library,
    static_top_library_permission,
    static_trigger_prohibition,
    static_type_overwrite,
    static_untap_cap,
    static_untap_each_untap_step,
)
from .static_rows.rows_combat import (
    static_all_must_block,
    static_attack_as_though_no_defender,
    static_attack_tax,
    static_attacks_if_able,
    static_block_additional,
    static_block_additional_n,
    static_block_any_number,
    static_cant_attack,
    static_cant_attack_or_block,
    static_cant_attack_or_block_lock,
    static_cant_be_blocked,
    static_cant_block,
    static_cant_block_and_cant_be_blocked,
    static_crew_saddle_power_bonus,
    static_must_be_blocked,
    static_must_be_blocked_by_one,
    static_qualified_combat_restriction_specs,
)
from .static_rows.rows_restrictions import (
    static_attached_activation_ban,
    static_cant_attack_you,
    static_cant_cast_spell_type,
    static_cant_have_counters,
    static_cant_lose_and_opponents_cant_win,
    static_cant_play_lands,
    static_instant_sorcery_cant_be_countered,
    static_spells_cant_be_countered,
)
from .static_rows.rows_grants import (
    static_animated_land,
    static_anthem,
    static_anthem_for_each,
    static_attached_anthem_keyword_and_quoted_grant,
    static_attached_double_quoted_grant,
    static_attached_keyword_and_quoted_grant,
    static_attached_look_top_and_quoted_grant,
    static_attached_quoted_anthem_grant,
    static_attached_quoted_anthem_grant_and_type,
    static_attached_quoted_grant,
    static_attached_quoted_grant_and_type,
    static_attached_untap_other_players,
    static_attached_ward_and_quoted_grant,
    static_burakos_self_types,
    static_cant_be_beamed_up,
    static_commander_creatures_quoted_grant,
    static_control_grant,
    static_grant,
    static_graveyard_beam_me_up_grant,
    static_graveyard_chosen_type,
    static_graveyard_retrace_grant,
    static_group_chosen_type,
    static_group_counter_grant,
    static_group_goaded,
    static_group_type_addition,
    static_hand_cycling_grant,
    static_is_chosen_type,
    static_multi_permanent_type_grant,
    static_opponent_creature_anthem,
    static_quoted_grant,
    static_self_anthem_per_opponent_color_permanent,
    static_soulbond_anthem,
    static_soulbond_grant,
    static_soulbond_quoted_grant,
)
from .static_rows.object_scope import object_filter  # noqa: F401
from .static_rows.combat_restrictions import ATTACHED_SUBJECT_PATTERN  # noqa: F401
from .static_rows.keyword_flags import flag_keywords_and_ward  # noqa: F401
from .static_rows.cost_patterns import commander_eligibility_line, deck_any_number_line  # noqa: F401
from .static_rows.granted_abilities import (  # noqa: F401
    quoted_ability_grant_effects,
    quoted_ability_grant_effects_list,
    type_addition_params,
)
from .static_rows.static_conditions import activation_attached_condition  # noqa: F401
from .static_rows.enter_choices import (  # noqa: F401
    copy_exception_params,
    enter_as_copy_specs,
    enter_as_copy_tail,
    enter_choice_specs,
)
from .static_rows.matcher_types import claim  # noqa: F401


STATIC_MATCHERS: tuple[Union[StaticMatcher, StaticRewrite], ...] = (
    StaticMatcher("fixed_base", static_fixed_base),
    StaticMatcher("match", static_match),
    StaticMatcher("blitz_cost_reduction", static_blitz_cost_reduction),
    StaticMatcher("blitz_graveyard_permission", static_blitz_graveyard_permission),
    StaticMatcher("match_2", static_match_2),
    StaticMatcher("pip_life_option", static_pip_life_option),
    StaticMatcher("storm_grant", static_storm_grant),
    StaticMatcher("during_other_turns_cost", static_during_other_turns_cost),
    StaticMatcher("trigger_doubler", static_trigger_doubler),
    StaticMatcher("extra_etb_counter_specs", static_extra_etb_counter_specs),
    StaticMatcher("enters_with_counters_count", static_enters_with_counters_count),
    StaticMatcher("self_graveyard_shuffle", static_self_graveyard_shuffle),
    StaticMatcher("commander_damage_triple", static_commander_damage_triple),
    StaticRewrite("fold_additional", static_fold_additional),
    StaticMatcher("damage_as_unblocked", static_damage_as_unblocked),
    StaticMatcher("toughness_damage", static_toughness_damage),
    StaticMatcher("compound_self", static_compound_self),
    StaticMatcher("quoted_tail", static_quoted_tail),
    StaticMatcher("flag_keywords", static_flag_keywords),
    StaticMatcher("colored_quoted_self", static_colored_quoted_self),
    StaticMatcher("quoted_self", static_quoted_self),
    StaticMatcher("turn_split_pt", static_turn_split_pt),
    StaticMatcher("turn_split_fixed_pt", static_turn_split_fixed_pt),
    StaticMatcher("each_permanent_gets_if_creature", static_each_permanent_gets_if_creature),
    StaticMatcher("conditional_otherwise", static_conditional_otherwise),
    StaticMatcher("conditional_static_specs", static_conditional_static_specs),
    StaticMatcher("pt_cda", static_pt_cda),
    StaticMatcher("pt_cda_that_number", static_pt_cda_that_number),
    StaticMatcher("pt_cda_single", static_pt_cda_single),
    StaticMatcher("cant_be_countered_self", static_cant_be_countered_self),
    StaticMatcher("grant_cant_be_countered", static_grant_cant_be_countered),
    StaticMatcher("grant_search_prohibited", static_grant_search_prohibited),
    StaticMatcher("grant_skip_extra_turns", static_grant_skip_extra_turns),
    StaticMatcher("lands_every_basic_type", static_lands_every_basic_type),
    StaticMatcher("flash_permission", static_flash_permission),
    StaticMatcher("cast_timing_flash_and_restriction", static_cast_timing_flash_and_restriction),
    StaticMatcher("named_card", static_named_card),
    StaticMatcher("activation_prohibition_opponents", static_activation_prohibition_opponents),
    StaticMatcher("cant_cast_defending_player", static_cant_cast_defending_player),
    StaticMatcher("cant_cast_opponents_your_turn", static_cant_cast_opponents_your_turn),
    StaticMatcher("cant_cast_opponents_hand_only", static_cant_cast_opponents_hand_only),
    StaticMatcher("cant_cast_or_activate_opponents", static_cant_cast_or_activate_opponents),
    StaticMatcher("activation_prohibition", static_activation_prohibition),
    StaticMatcher("spell_cost_tax", static_spell_cost_tax),
    StaticMatcher("spell_cost_tax_color", static_spell_cost_tax_color),
    StaticMatcher("spell_cost_tax_commander", static_spell_cost_tax_commander),
    StaticMatcher("spell_cost_tax_that_target", static_spell_cost_tax_that_target),
    StaticMatcher("spell_cost_tax_opponents", static_spell_cost_tax_opponents),
    StaticMatcher("spell_cost_tax_you_cast", static_spell_cost_tax_you_cast),
    StaticMatcher("equip_activation_discount", static_equip_activation_discount),
    StaticMatcher("equip_self_discount", static_equip_self_discount),
    StaticMatcher("activation_cost_reduction_type", static_activation_cost_reduction_type),
    StaticMatcher("ability_cost_modifier", static_ability_cost_modifier),
    StaticMatcher("keyword_cost_modifier", static_keyword_cost_modifier),
    StaticMatcher("additional_activation_cost", static_additional_activation_cost),
    StaticMatcher("self_cost_reduction_where_x", static_self_cost_reduction_where_x),
    StaticMatcher("self_cost_reduction_for_each", static_self_cost_reduction_for_each),
    StaticMatcher("second_spell_cost_reduction", static_second_spell_cost_reduction),
    StaticMatcher("self_cost_reduction_colored", static_self_cost_reduction_colored),
    StaticMatcher("self_cost_reduction_if", static_self_cost_reduction_if),
    StaticMatcher("cast_limit_noncreature", static_cast_limit_noncreature),
    StaticMatcher("cast_limit", static_cast_limit),
    StaticMatcher("extra_land_drop", static_extra_land_drop),
    StaticMatcher("no_max_hand_size", static_no_max_hand_size),
    StaticMatcher("cant_lose_for_life", static_cant_lose_for_life),
    StaticMatcher("ignore_legend_rule", static_ignore_legend_rule),
    StaticMatcher("color_statement_specs", static_color_statement_specs),
    StaticMatcher("hand_size_modifier", static_hand_size_modifier),
    StaticMatcher("skip_untap_steps", static_skip_untap_steps),
    StaticMatcher("players_cant_draw", static_players_cant_draw),
    StaticMatcher("players_cant_gain_life", static_players_cant_gain_life),
    StaticMatcher("damage_cant_be_prevented", static_damage_cant_be_prevented),
    StaticMatcher("skip_your_step", static_skip_your_step),
    StaticMatcher("graveyard_library_cast_prohibition", static_graveyard_library_cast_prohibition),
    StaticMatcher("graveyard_library_entry_prohibition", static_graveyard_library_entry_prohibition),
    StaticMatcher("radiation_life_gain", static_radiation_life_gain),
    StaticMatcher("linked_exile_permission", static_linked_exile_permission),
    StaticMatcher("top_library_permission", static_top_library_permission),
    StaticMatcher("top_library", static_top_library),
    StaticMatcher("graveyard_cast", static_graveyard_cast),
    StaticMatcher("graveyard_land_play_permission", static_graveyard_land_play_permission),
    StaticMatcher("look_at_top_any_time", static_look_at_top_any_time),
    StaticMatcher("not_a_creature", static_not_a_creature),
    StaticMatcher("activate_as_though_haste", static_activate_as_though_haste),
    StaticMatcher("untap_each_untap_step", static_untap_each_untap_step),
    StaticMatcher("no_untap_optional", static_no_untap_optional),
    StaticMatcher("no_untap", static_no_untap),
    StaticMatcher("no_untap_attached", static_no_untap_attached),
    StaticMatcher("attached_ability_loss", static_attached_ability_loss),
    StaticMatcher("attached_loses_abilities_transform", static_attached_loses_abilities_transform),
    StaticMatcher("attached_land_basic_type", static_attached_land_basic_type),
    StaticMatcher("attached_creature_types", static_attached_creature_types),
    StaticMatcher("attached_permanent_is", static_attached_permanent_is),
    StaticMatcher("self_type_addition", static_self_type_addition),
    StaticMatcher("no_untap_group_power", static_no_untap_group_power),
    StaticMatcher("no_untap_nonbasic_lands", static_no_untap_nonbasic_lands),
    StaticMatcher("untap_cap", static_untap_cap),
    StaticMatcher("trigger_prohibition", static_trigger_prohibition),
    StaticMatcher("opponents_enter_tapped", static_opponents_enter_tapped),
    StaticMatcher("all_enter_tapped", static_all_enter_tapped),
    StaticMatcher("type_overwrite", static_type_overwrite),
    StaticMatcher("animated_land", static_animated_land),
    StaticMatcher("land_is_basic_type", static_land_is_basic_type),
    StaticMatcher("all_basic_type_becomes", static_all_basic_type_becomes),
    StaticMatcher("attached_anthem_protection", static_attached_anthem_protection),
    StaticMatcher("group_anthem_protection", static_group_anthem_protection),
    StaticMatcher("self_protection", static_self_protection),
    StaticMatcher("attached_protection", static_attached_protection),
    StaticMatcher("group_protection", static_group_protection),
    StaticMatcher("attached_anthem_for_each", static_attached_anthem_for_each),
    StaticMatcher("attached_remove_keyword", static_attached_remove_keyword),
    StaticMatcher("attached_type_addition", static_attached_type_addition),
    StaticMatcher("attached_trailing_type", static_attached_trailing_type),
    StaticMatcher("attached_anthem", static_attached_anthem),
    StaticMatcher("attached_grant", static_attached_grant),
    StaticMatcher("attached_goaded", static_attached_goaded),
    StaticMatcher("attached_anthem_x", static_attached_anthem_x),
    StaticMatcher("self_anthem_for_each_gy_subtype", static_self_anthem_for_each_gy_subtype),
    StaticMatcher("self_anthem_for_each", static_self_anthem_for_each),
    StaticMatcher("anthem_devotion_self", static_anthem_devotion_self),
    StaticMatcher("self_anthem", static_self_anthem),
    StaticMatcher("self_grant", static_self_grant),
    StaticMatcher("attack_as_though_no_defender", static_attack_as_though_no_defender),
    StaticMatcher("crew_saddle_power_bonus", static_crew_saddle_power_bonus),
    StaticMatcher("block_additional_n", static_block_additional_n),
    StaticMatcher("attack_tax", static_attack_tax),
    StaticMatcher("cant_attack_you", static_cant_attack_you),
    StaticMatcher("attached_activation_ban", static_attached_activation_ban),
    StaticMatcher("cant_cast_spell_type", static_cant_cast_spell_type),
    StaticMatcher("cant_play_lands", static_cant_play_lands),
    StaticMatcher("cant_lose_and_opponents_cant_win", static_cant_lose_and_opponents_cant_win),
    StaticMatcher("spells_cant_be_countered", static_spells_cant_be_countered),
    StaticMatcher("instant_sorcery_cant_be_countered", static_instant_sorcery_cant_be_countered),
    StaticMatcher("cant_have_counters", static_cant_have_counters),
    StaticMatcher("cant_attack_or_block_lock", static_cant_attack_or_block_lock),
    StaticMatcher("cant_attack_or_block", static_cant_attack_or_block),
    StaticMatcher("cant_block_and_cant_be_blocked", static_cant_block_and_cant_be_blocked),
    StaticMatcher("cant_attack", static_cant_attack),
    StaticMatcher("cant_block", static_cant_block),
    StaticMatcher("cant_be_blocked", static_cant_be_blocked),
    StaticMatcher("attacks_if_able", static_attacks_if_able),
    StaticMatcher("must_be_blocked", static_must_be_blocked),
    StaticMatcher("must_be_blocked_by_one", static_must_be_blocked_by_one),
    StaticMatcher("all_must_block", static_all_must_block),
    StaticMatcher("block_additional", static_block_additional),
    StaticMatcher("block_any_number", static_block_any_number),
    StaticMatcher("qualified_combat_restriction_specs", static_qualified_combat_restriction_specs),
    StaticMatcher("control_grant", static_control_grant),
    StaticMatcher("is_chosen_type", static_is_chosen_type),
    StaticMatcher("graveyard_chosen_type", static_graveyard_chosen_type),
    StaticMatcher("group_type_addition", static_group_type_addition),
    StaticMatcher("group_chosen_type", static_group_chosen_type),
    StaticMatcher("group_goaded", static_group_goaded),
    StaticMatcher("soulbond_quoted_grant", static_soulbond_quoted_grant),
    StaticMatcher("soulbond_anthem", static_soulbond_anthem),
    StaticMatcher("soulbond_grant", static_soulbond_grant),
    StaticMatcher("attached_untap_other_players", static_attached_untap_other_players),
    StaticMatcher("attached_quoted_anthem_grant", static_attached_quoted_anthem_grant),
    StaticMatcher("attached_quoted_anthem_grant_and_type", static_attached_quoted_anthem_grant_and_type),
    StaticMatcher("attached_anthem_keyword_and_quoted_grant", static_attached_anthem_keyword_and_quoted_grant),
    StaticMatcher("attached_keyword_and_quoted_grant", static_attached_keyword_and_quoted_grant),
    StaticMatcher("attached_ward_and_quoted_grant", static_attached_ward_and_quoted_grant),
    StaticMatcher("attached_double_quoted_grant", static_attached_double_quoted_grant),
    StaticMatcher("attached_look_top_and_quoted_grant", static_attached_look_top_and_quoted_grant),
    StaticMatcher("attached_quoted_grant_and_type", static_attached_quoted_grant_and_type),
    StaticMatcher("attached_quoted_grant", static_attached_quoted_grant),
    StaticMatcher("burakos_self_types", static_burakos_self_types),
    StaticMatcher("opponent_creature_anthem", static_opponent_creature_anthem),
    StaticMatcher("self_anthem_per_opponent_color_permanent", static_self_anthem_per_opponent_color_permanent),
    StaticMatcher("anthem_for_each", static_anthem_for_each),
    StaticMatcher("anthem", static_anthem),
    StaticMatcher("commander_creatures_quoted_grant", static_commander_creatures_quoted_grant),
    StaticMatcher("quoted_grant", static_quoted_grant),
    StaticMatcher("group_counter_grant", static_group_counter_grant),
    StaticMatcher("each_creature_thats", static_each_creature_thats),
    StaticMatcher("legendary_permanents_grant", static_legendary_permanents_grant),
    StaticMatcher("graveyard_retrace_grant", static_graveyard_retrace_grant),
    StaticMatcher("graveyard_beam_me_up_grant", static_graveyard_beam_me_up_grant),
    StaticMatcher("cant_be_beamed_up", static_cant_be_beamed_up),
    StaticMatcher("multi_permanent_type_grant", static_multi_permanent_type_grant),
    StaticMatcher("grant", static_grant),
    StaticMatcher("hand_cycling_grant", static_hand_cycling_grant),
)


def static_effect_specs(clause: str) -> Optional[list[EffectSpec]]:
    """`EffectSpec`s for a static anthem/keyword-grant ``clause``, or ``None``.

    Full-matches the clause (like the one-shot handler table) so a partial or
    "until end of turn" phrasing isn't claimed. A compound "get +N/+N and have
    <keywords>" emits both an ``anthem`` and a ``grant_keyword`` spec. The specs
    carry ``affects`` + optional ``subtype``/``tokens`` for the layer engine.
    Also claims the attached-permanent shape ("equipped/enchanted creature
    gets +N/+N [and has <keywords>]", "equipped/enchanted creature has
    <keywords>") with ``affects="attached_permanent"`` — see
    `_ATTACHED_SUBJECTS` above.
    """
    text = clause.strip().rstrip(".").strip()
    ctx = StaticContext(clause=clause, text=text)
    for step in STATIC_MATCHERS:
        if isinstance(step, StaticRewrite):
            ctx = replace(ctx, text=step.rewrite(ctx.text))
            continue
        result = step.match(ctx)
        if result is None:
            continue
        # PAR-289 M4: a row that recognised the clause but could not model it (a keyword list it cannot grant, a
        # subject its own scope cannot express) leaves it to the composite group/host grammar, which either models
        # every clause or declines whole.
        return _composite_fallback(ctx) if result is DECLINE else result
    return _composite_fallback(ctx)


def _composite_fallback(ctx: StaticContext) -> Optional[list[EffectSpec]]:
    result = static_typed_group_statement(ctx)
    return None if result is None or result is DECLINE else result


# `library_permission` (imported above) evaluates "as long as …" conditions through this hook; see `clause_hooks`.
register_static_condition(static_condition)
# The row modules (`static_rows/`) re-enter the table through the same kind of late-bound forwarder.
register_static_effect_specs(static_effect_specs)
