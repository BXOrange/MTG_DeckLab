// Static label/icon tables and choice-kind sets for the shared game board.
// Pure data (plus two lookups): nothing here touches board state.

import { t } from '../i18n.js';

export const PHASE_LABELS = {
  beginning: t('bd.phase.beginning'),
  precombat_main: t('bd.phase.precombat_main'),
  combat: t('bd.phase.combat'),
  postcombat_main: t('bd.phase.postcombat_main'),
  ending: t('bd.phase.ending'),
};
export const STEP_LABELS = {
  untap: t('bd.step.untap'),
  upkeep: t('bd.step.upkeep'),
  draw: t('bd.step.draw'),
  main1: t('bd.step.main1'),
  begin_combat: t('bd.step.begin_combat'),
  declare_attackers: t('bd.step.declare_attackers'),
  declare_blockers: t('bd.step.declare_blockers'),
  first_strike_damage: t('bd.step.first_strike_damage'),
  combat_damage: t('bd.step.combat_damage'),
  end_combat: t('bd.step.end_combat'),
  main2: t('bd.step.main2'),
  end: t('bd.step.end'),
  cleanup: t('bd.step.cleanup'),
  // Not a real step name on its own — `DelayedTrigger.step` uses this for
  // "your next main phase" (Mana Drain-shaped), matching whichever of
  // main1/main2 begins first (`GameEngine._fire_delayed_triggers`).
  main: t('bd.step.main'),
};
export function labelPhase(name) {
  return PHASE_LABELS[name] || name || '—';
}
export function labelStep(name) {
  return STEP_LABELS[name] || name || '—';
}

// Icon per choice kind — search, cascade and discover share the same
// "answer one of these options" shape, so one renderer covers them.
// Kinds answered with a checkbox subset (`selection_id` + `option_ids`); they share one draft.
export const SELECTION_KINDS = new Set(['proliferate', 'graveyard_replacement']);

export const CHOICE_ICONS = {
  proliferate: '🌱', graveyard_replacement: '⚖️', search: '🔎', cascade: '🌊', discover: '🔮', replacement_order: '⚖️',
  land_tapped: '💧', land_tapped_reveal: '💧', order_triggers: '🔀', trigger_target: '🎯', opponent_target: '🎯', opponent_chooser: '🧑‍⚖️',
  opponent_sacrifice_chooser: '🧑‍⚖️',
  enter_as_copy: '🪞', counter_unless_pays: '🚫', ward: '🛡️', trigger_doubler_tap: '🔁',
  flicker_return_timing: '🔁',
  commander_zone: '👑', trigger_mode: '🎭', add_mana_any_color: '💎', door_choice: '🚪',
  choose_creature_type: '🐾', choose_color: '🎨', choose_basic_land_type: '🗺️', read_ahead: '📜',
  // PAR-203 (RULE 608.2d): "choose a creature type / color / card name" made as a spell or ability resolves.
  choose_for_source: '🏷️',
  scry: '🔮', reorder_top: '🔮', look_hand: '👁️', surveil: '🕵️', clash: '⚔️', opening_hand_battlefield: '🌅', dredge: '⚰️',
  explore_bin: '🧭', populate: '🌱', bolster: '💪', blight: '🥀', endure: '🕊️', recruit: '🎖️',
  // PAR-148: which defender a creature put into combat attacks / who takes "that player or a planeswalker" damage.
  reselect_attack: '⚔️', damage_recipient: '🎯',
  meteor_permanent: '☄️',
  // MEC-108: "your choice of a flying counter or a lifelink counter" — at resolution / as it enters.
  counter_kind: '🏷️', choose_enter_counter: '🏷️', riot: '🏷️', tribute: '🏷️', tribute_opponent: '👥',
  // Explorer's Scope's "look at the top card, if it's a land you may put
  // it onto the battlefield tapped" (bug report, 2026-09-04).
  peek_top_land: '🔭',
  // RULE 701.38 vote / RULE 701.55 villainous choice (MEC-46 / ENG-33).
  vote: '🗳️', vote_object: '🗳️', villainous_choice: '😈',
  // RULE 724 / Word of Command — pick a card from the target's hand (MEC-51b).
  word_of_command: '🗣️',
};

// VIS-13: the player-state zones whose cards have no controller, so a target
// candidate found there is tagged with its owner instead.
export const TARGET_OWNER_ZONES = ['graveyard', 'exile', 'hand', 'command'];
// Pending-choice kinds that are RULE 115 target selections (an ability's
// target, picked from the generic choice popup) — the ones whose candidates
// can also be clicked on the board once the popup is pushed aside (VIS-14).
// MEC-118: `opponent_target` is the same pick made by the opponent a spell's controller named ("of an opponent's choice").
export const TARGET_CHOICE_KINDS = new Set(['trigger_target', 'trigger_target_multi', 'copy_targets', 'opponent_target']);
