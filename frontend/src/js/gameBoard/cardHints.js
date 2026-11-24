// Pure text/label helpers for card actions, effects and restrictions (no board state).

import { t } from '../i18n.js';
import { renderOracleText } from '../cardTile.js';
import { escapeHtml } from './html.js';

// RULE 606: color-code a loyalty ability's button by its [+N]/[-N]/[0]
// sign, so it reads at a glance distinctly from an ordinary activated
// ability — the wire action only carries the pre-rendered cost_label
// string (e.g. "[+2]"), not a raw signed int.
const LOYALTY_COST_RE = /^\[([+-]?\d+)\]$/;

export function faceHint(a) {
  if (a.face === 'assist') return ' (Assist)';
  if (a.face === 'fuse') return t('bd.faceHint.fuse');
  if (a.face === 'prototype' || a.face === 'overload') {
    const keyword = a.face === 'prototype' ? 'Prototype' : 'Overload';
    return a.cost_label ? ` (${keyword} — ${renderOracleText(a.cost_label)})` : ` (${keyword})`;
  }
  // RULE 702.103: the Bestow cast is the same card name as the plain
  // creature cast, so it gets a short "(Bestow — <cost>)" suffix rather
  // than a redundant repeated name, the same treatment as Fuse above.
  if (a.face === 'bestow') {
    return a.bestow_cost_label ? ` (Bestow — ${renderOracleText(a.bestow_cost_label)})` : ' (Bestow)';
  }
  // RULE 702.37a/702.168a: the morph/disguise offer casts the card FACE
  // DOWN as a nameless 2/2 for its face-down cost ({3}) — a wholly
  // different play from the ordinary front-face cast (a separate button
  // with no `face`). Label it as such so the two aren't mistaken for a
  // redundant pair of "cast" buttons (which is exactly what
  // ` — <card name>` looked like).
  if (a.face === 'face_down') {
    const kind = a.face_down_kind ? t(`bd.faceDown.${a.face_down_kind}`) : t('bd.faceDown.default');
    return t('bd.faceHint.faceDown', { kind, cost: a.cost_label || '{3}' });
  }
  // RULE 702.162a: More Than Meets the Eye casts the same card converted, back face up, for its own alternative
  // cost — labelled with that cost and the back face's name so it is not mistaken for the plain cast.
  if (a.more_than_meets_the_eye) {
    return t('bd.faceHint.converted', { cost: escapeHtml(a.mtmte_cost_label || a.cost_label || ''), name: escapeHtml(a.back_name || '') });
  }
  return a.face ? ` — ${escapeHtml(a.name)}` : '';
}

// A card with a second castable face — a modal DFC's back (RULE 712.10),
// a split card's other half (RULE 709.3), or an Adventure's spell half
// (RULE 716.2b) — offers a second, independent action for the same hand
// card; `faceHint` labels it with its own name so the two buttons are
// distinguishable. Fuse (RULE 709.4) casts the same combined name shown
// on the plain button, so it gets a short suffix instead of a redundant
// repeated name. The front face keeps today's plain label (no visible
// change for the common single-face case).
// RULE 702.174a: the "cast, promising a gift to <opponent>" offer — one entry per opponent,
// so the label names who receives it.
export function giftHint(a) {
  const gift = a.gift_opponent_id
    ? escapeHtml(t('bd.cast.giftHint', { name: a.gift_opponent_name || a.gift_opponent_id }))
    : '';
  const splice = a.splice_ids?.length ? ` + Splice (${(a.splice_names || []).map(escapeHtml).join(', ')})` : '';
  return gift + splice;
}

export function modeHint(a) {
  if (!a.mode_description) return a.entwine ? t('bd.modeHint.entwine') : '';
  const suffix = a.entwine ? t('bd.modeHint.entwine') : '';
  return ` — ${escapeHtml(a.mode_description)}${suffix}`;
}

// RULE 700.2: a modal spell offers one `cast_spell` action per mode (or
// per legal mode combination — `_modal_cast_actions`), each tagged with
// `mode`/`mode_description`. Without this, every offered variant renders
// as an identical "✨ Zaubern" button and `findTargetableAction` picks
// whichever happens to come first in `legal_actions` — the player never
// actually chooses a mode. `a.entwine` (RULE 702.42a) reuses the same
// "both modes" `mode: "both"` shape, just priced, so it gets its own
// label rather than falling back to the plain mode text.
// PAR-255/BUG-59: a modal activated ability offers one `activate_ability` per mode (same ability_index), so
// lookups must match the mode as well.
export function sameActivationMode(a, mode) {
  return (a.mode ?? null) === (mode ?? null);
}

// Which exiled cards are castable from there right now, and why (RULE
// 601.3b analogue / 715.3d / 723.3c) — the three independent mechanisms
// `GameEngine._castable_from_exile`/`_has_temp_play_permission` check.
// Returns ``null`` for an ordinary, inert exiled card.
export function exileCastableInfo(o, s) {
  if (o.adventure_castable) {
    return { reason: t('bd.exileCast.adventureReason'), duration: t('bd.exileCast.adventureDuration') };
  }
  if (o.prepared_copy) {
    return { reason: t('bd.exileCast.preparedReason'), duration: t('bd.exileCast.preparedDuration') };
  }
  const grantedTurn = s.temp_play_permissions ? s.temp_play_permissions[o.instance_id] : null;
  if (grantedTurn != null) {
    const source = s.temp_play_permission_source ? s.temp_play_permission_source[o.instance_id] : null;
    return {
      reason: source ? t('bd.exileCast.impulseReason', { source }) : t('bd.exileCast.tempReason'),
      duration: t('bd.exileCast.tempDuration', { turn: grantedTurn + 1 }),
    };
  }
  return null;
}

export function loyaltyModifierClass(costLabel) {
  const m = LOYALTY_COST_RE.exec(costLabel || '');
  if (!m) return '';
  const n = parseInt(m[1], 10);
  if (n > 0) return ' gf-card-action--loyalty-plus';
  if (n < 0) return ' gf-card-action--loyalty-minus';
  return ' gf-card-action--loyalty-zero';
}

// The German label for a trace entry's `duration` (game/continuous.py):
// how long the effect lasts, shown as a chip in the per-card summary.
export function durationLabel(d) {
  if (d === 'end_of_turn') return t('bd.dur.endOfTurn');
  if (d === 'permanent') return t('bd.dur.permanent');
  return t('bd.dur.static'); // "static": lasts while its source stays in play
}

export function durationTitle(d) {
  if (d === 'end_of_turn') return t('bd.durTitle.endOfTurn');
  if (d === 'permanent') return t('bd.durTitle.permanent');
  return t('bd.durTitle.static');
}

export function keywordAbbrev(label) {
  const map = {
    Flying: 'FLY',
    Reach: 'RCH',
    'First Strike': 'FS',
    'Double Strike': 'DS',
    Deathtouch: 'DT',
    Trample: 'TR',
    Vigilance: 'VIG',
    Lifelink: 'LL',
    Menace: 'MEN',
    Defender: 'DEF',
    Haste: 'HST',
    Indestructible: 'IND',
  };
  if (map[label]) return map[label];
  if (label.startsWith('Protection')) return 'PRO';
  return label;
}

// Human label for an opaque restriction dict (`game/mana_abilities.py`'s
// `_parse_restriction` whitelist — this module has no server-side label
// string to read, unlike `TargetSpec.label()` for targets, so the mapping
// lives here).
export function restrictionLabel(restriction) {
  const kind = restriction?.kind;
  if (kind === 'contains_x') return t('bd.restrict.containsX');
  if (kind === 'creature_spell') {
    return restriction.allow_ability
      ? t('bd.restrict.creatureSpellAbility')
      : t('bd.restrict.creatureSpell');
  }
  if (kind === 'commander_spell') return t('bd.restrict.commanderSpell');
  if (kind === 'legendary_spell') return t('bd.restrict.legendarySpell');
  if (kind === 'instant_or_sorcery_spell') return t('bd.restrict.instantSorcery');
  if (kind === 'type_spell' || kind === 'card_type_spell' || kind === 'type_list_spell') {
    const types = (restriction.types || []).join('/');
    return restriction.allow_ability
      ? t('bd.restrict.typeSpellAbility', { types })
      : t('bd.restrict.typeSpell', { types });
  }
  return 'zweckgebunden';
}
