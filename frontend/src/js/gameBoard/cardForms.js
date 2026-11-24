// Pure markup for card action controls and effect summaries (no board state).

import { MANA_SYMBOL_EMOJI, renderOracleText } from '../cardTile.js';
import { cardImageUrl } from '../api.js';
import { durationLabel, durationTitle, faceHint, giftHint, modeHint, loyaltyModifierClass } from './cardHints.js';
import { xKey, manaOptionLabel, kickerFieldHtml, replicateFieldsHtml } from './castForm.js';
import { t } from '../i18n.js';
import { escapeHtml, escapeAttr } from './html.js';

// Per-card "info point" (RULE 613): a Σ-badge that opens a breakdown of
// every effect reshaping this permanent — Auren, Ausrüstung, Marken,
// Anthem-/Bis-Zugende-Buffs — each with its source and duration, plus the
// resulting characteristics (the "Summe"). Built from the object's
// `static_trace`, so it only appears once something actually changed it.
//
// Uses the native Popover API (`popover` + `popovertarget`) so the panel
// renders in the browser's top layer — never clipped by a card's/row's
// `overflow` nor painted under a later card — and light-dismisses. It's
// positioned at the badge by `wire()`'s `toggle` handler (the top layer
// otherwise centres it).
export function effectSummaryHtml(o) {
  const trace = [...(o.static_trace || [])];
  if (o.is_creature && o.damage_marked) trace.push({ source: 'Schaden in diesem Zug', description: `−${o.damage_marked} Widerstandskraft (Anzeige)`, power: o.power, toughness: o.toughness - o.damage_marked, duration: 'end_of_turn' });
  if (!trace.length || o.instance_id == null) return '';
  const popId = `gf-eff-pop-${o.instance_id}`;
  const ptResult = o.power != null && o.toughness != null ? `${o.power}/${o.toughness - (o.damage_marked || 0)}` : null;
  const keywords = (o.keywords || []).join(', ');
  const resultParts = [];
  if (ptResult) resultParts.push(`<strong>${escapeHtml(ptResult)}</strong>`);
  if (keywords) resultParts.push(escapeHtml(keywords));
  const rows = trace
    .map((t) => {
      const pt = t.power != null && t.toughness != null
        ? `<span class="gf-eff-pt">→ ${escapeHtml(`${t.power}/${t.toughness}`)}</span>`
        : '';
      return `<li>
        <span class="gf-eff-src">${escapeHtml(t.source)}</span>
        <span class="gf-eff-desc">${escapeHtml(t.description)}</span>${pt}
        <span class="gf-eff-dur gf-eff-dur--${escapeAttr(t.duration || 'static')}" title="${escapeAttr(durationTitle(t.duration))}">${escapeHtml(durationLabel(t.duration))}</span>
      </li>`;
    })
    .join('');
  return `<span class="gf-effects">
    <button type="button" class="gf-effects-badge" popovertarget="${escapeAttr(popId)}" title="${escapeAttr(t('bd.eff.badgeTitle'))}">Σ</button>
    <div id="${escapeAttr(popId)}" popover class="gf-effects-pop">
      <div class="gf-eff-result">${escapeHtml(t('bd.eff.result', { parts: resultParts.join(' · ') || '—' }))}</div>
      <ul class="gf-eff-list">${rows}</ul>
    </div>
  </span>`;
}

// RULE 605.1a "any combination of colours" split builder: one number input
// per real color (never colorless — RULE 605.1a's "any color" excludes it,
// `mana_abilities._ALL_COLORS`), constrained client-side to sum to exactly
// `combination_total` before the confirm button sends `color_split`
// (`kind` picks which action type the confirm dispatches — the shape is
// otherwise identical for a battlefield `tap_for_mana` ability and a
// hand-zone `activate_hand_mana` one). The colour set itself comes from
// `a.options` (one option per colour the ability actually prints) rather
// than a hardcoded WUBRG list — a *restricted* combination ability (Vivi
// Ornitier's own "any combination of {U} and/or {R}") only ever offers
// its own printed subset here, same as the single-colour dropdown above
// already do; a bare "any combination of colours" (Flamebraider/Selvala)
// still lists all five, since its own `options` already does too.
export function colorSplitHtml(a, kind) {
  const total = a.has_x ? 'x' : a.combination_total;
  const max = a.has_x ? a.max_x : a.combination_total;
  const label = a.has_x ? 'X' : a.combination_total;
  const colors = (a.options || [])
    .map((opt) => Object.keys(opt.mana || {})[0])
    .filter(Boolean);
  const inputs = colors
    .map(
      (c) =>
        `<label class="gf-split-color" title="${c}">${MANA_SYMBOL_EMOJI[c]}<input type="number" min="0" max="${max}" value="0" data-split-color="${c}" /></label>`
    )
    .join('');
  const actionInfo = JSON.stringify({ type: kind, instance_id: a.instance_id, ability_index: a.ability_index });
  return `
    <div class="gf-mana-split" data-split-total="${total}" data-split-action='${escapeAttr(actionInfo)}'>
      <span class="gf-split-hint">Farbkombination (${label}):</span>
      ${inputs}
      <button type="button" class="gf-card-action" data-split-confirm>${t('bd.split.generate')}</button>
    </div>`;
}

export function manaChoiceControlHtml(a, options, type, buttonText, { hasX = false, sacrificeCost = false } = {}) {
  const info = JSON.stringify({
    type, iid: a.instance_id, ability_index: a.ability_index, has_x: hasX,
  });
  const choiceInfo = JSON.stringify({
    type, iid: a.instance_id, ability_index: a.ability_index, option_from_select: true,
  });
  const buttonAction = sacrificeCost
    ? `data-sacrifice-choice-start='${escapeAttr(choiceInfo)}'`
    : `data-mana-choice-activate='${escapeAttr(info)}'`;
  const optionHtml = options
    .map((option) => `<option value="${option.index}">${escapeHtml(manaOptionLabel(option))}</option>`)
    .join('');
  const xInput = hasX
    ? `<input type="number" min="${a.min_x || 0}" max="${a.max_x}" value="${a.max_x}" data-x-input="${a.instance_id}" />`
    : '';
  return `
    <div class="gf-mana-choice${hasX ? ' gf-mana-choice--x' : ''}">
      ${xInput}
      <select data-mana-option aria-label="${escapeAttr(t('bd.mana.chooseOutput'))}">${optionHtml}</select>
      <button type="button" class="gf-card-action" ${buttonAction}>${buttonText}</button>
    </div>`;
}

export function castTargetHtml(a) {
  const iid = a.instance_id;
  const xField = a.has_x
    ? a.allowed_x?.length
      ? `<select data-x-input="${escapeAttr(xKey(iid, a.face, a.blitz, a.splice_ids))}">${a.allowed_x.map((value) => `<option value="${escapeAttr(value)}" ${value === a.max_x ? 'selected' : ''}>${escapeHtml(value)}</option>`).join('')}</select>`
      : `<input type="number" min="${a.min_x || 0}" max="${a.max_x}" value="${a.max_x}" data-x-input="${xKey(iid, a.face, a.blitz, a.splice_ids)}" />`
    : '';
  const startInfo = JSON.stringify({
    iid, type: a.type, ability_index: a.ability_index, face: a.face,
    mode: a.mode, entwine: a.entwine, alt_cost: !!a.alt_cost, warp: a.warp, evoke: a.evoke, surge: a.surge, blitz: a.blitz, pay_additional: a.pay_additional,
    bargained: a.bargained, gift_opponent_id: a.gift_opponent_id, splice_ids: a.splice_ids, free: !!a.free,
  });
  const label = a.type === 'activate_ability'
    ? `${renderOracleText(t('bd.cast.activateLabel', { cost: a.cost_label || t('bd.cast.activateDefault') }))}${modeHint(a)}`
    : `${renderOracleText(t(a.blitz != null ? 'bd.cast.blitzLabel' : a.surge ? 'bd.cast.surgeLabel' : a.evoke ? 'bd.cast.evokeLabel' : 'bd.cast.castLabel', { mode: a.warp ? `${modeHint(a)} Warp (${a.warp_cost_label || a.cost_label})` : a.blitz != null ? `${modeHint(a)} (${a.blitz_cost_label || a.cost_label})` : modeHint(a), face: faceHint(a) }))}${a.pay_additional ? ` + ${a.additional_cost_label || 'Zusatzkosten'}` : ''}${a.bargained ? ' + Bargain' : ''}${giftHint(a)}`;
  const lc = a.type === 'activate_ability' ? loyaltyModifierClass(a.cost_label) : '';
  const lockedHint = a.locked ? `<span class="hint">Ohne Kicker: ${escapeHtml(a.lock_reason || t('bd.cast.noValidTarget'))}</span>` : '';
  return `<div class="gf-cast-targets">${lockedHint}${xField}${kickerFieldHtml(a)}${replicateFieldsHtml(a)}<button type="button" class="gf-card-action${lc}" data-cast-target-start='${escapeAttr(startInfo)}'>${label}</button></div>`;
}

// Unavailable options are informational only: never manufacture legal actions
// or action payloads from Oracle text. Keep costs and ability text visible.
export function unavailableCardActionsHtml(o) {
  const labels = [];
  if (o.zone === 'hand' || o.zone === 'command' || o.adventure_castable || o.prepared_copy) {
    labels.push(o.is_land ? t('bd.cast.playLand', { face: '' })
      : `${t('bd.cast.castPlain', { mode: '', hint: '', face: '' })} ${o.mana_cost || '{0}'}`);
  }
  if (!o.face_down) {
    for (const line of (o.oracle_text || '').split('\n')) {
      // A printed activated ability has a cost before the colon. Exclude
      // colons inside reminder text rather than displaying those as actions.
      const text = line.replace(/\([^)]*\)/g, '').trim();
      if (text.includes(':')) labels.push(text);
    }
    if (o.zone === 'battlefield' && o.is_land && !labels.length) {
      const basicMana = { Plains: 'W', Island: 'U', Swamp: 'B', Mountain: 'R', Forest: 'G' };
      for (const [subtype, symbol] of Object.entries(basicMana)) {
        if ((o.type_line || '').split(/\s+/).includes(subtype)) labels.push(`{T}: {${symbol}}`);
      }
    }
  }
  if (!labels.length) labels.push(t('bd.menu.noActions'));
  return `<div class="gf-card-actions">${labels.map(label => `<button type="button" class="gf-card-action" disabled title="${escapeAttr(t('bd.menu.unavailable'))}">${renderOracleText(label)}</button>`).join('')}</div>`;
}

// scry/surveil (RULE 701.18/701.31): the away and order phases both offer
// exactly the looked-at cards plus a decline, but unlike a generic search
// the player needs to actually *read* each card to decide — a bare name
// button forces a hover to see it, so this renders an inline face thumbnail
// per option (`opt.card_id`, see `_look_top_choice`) alongside the label,
// still hoverable for the full-size tooltip via `data-hover-card`.
export function lookTopChoiceHtml(pending) {
  const options = pending.options || [];
  const cards = options
    .map((opt) => {
      if (opt.id === 'decline') {
        const action = JSON.stringify({ type: 'decline' });
        return `<button type="button" class="gf-lt-card gf-lt-decline" data-action='${escapeAttr(action)}'>
          <span class="gf-lt-decline-label">${escapeHtml(opt.label || 'Fertig')}</span>
        </button>`;
      }
      const action = JSON.stringify({ type: 'choose', option_id: opt.id, instance_id: opt.instance_id, name: opt.label });
      const img = opt.card_id ? cardImageUrl(opt.card_id, 'small', 'front') : null;
      return `<button type="button" class="gf-lt-card" data-hover-card="${escapeHtml(opt.label || '')}" data-action='${escapeAttr(action)}'>
        ${img ? `<img class="gf-lt-card-img" src="${escapeAttr(img)}" alt="${escapeAttr(opt.label || '')}" loading="lazy">` : ''}
        <span class="gf-lt-card-label">${escapeHtml(opt.label || opt.id)}</span>
      </button>`;
    })
    .join('');
  return `<div class="gf-lt-options">${cards}</div>`;
}

// "Mana-Potenzial": the maximum mana and coherent source-choice
// variations from this player's untapped/unexiled sources. ``potential``
// is `view.mana_potential[player_id]`
// (absent for a seat this view doesn't own — RULE 400.2, same as the
// hand array itself).
export function manaPotentialHtml(potential) {
  if (!potential) return '';
  const order = ['W', 'U', 'B', 'R', 'G', 'C'];
  const manaParts = (amounts) => order
    .filter((c) => amounts?.[c] > 0)
    .map((c) => `<span class="gf-mana">${MANA_SYMBOL_EMOJI[c]}${amounts[c]}</span>`)
    .join('');
  const variations = (potential.variations || [])
    .map((variation) => `
      <li class="gf-mana-potential-variation">
        <strong>${variation.total}</strong>${manaParts(variation.mana || {})}
      </li>`)
    .join('');
  const details = variations
    ? `<div class="gf-mana-potential-heading">${escapeHtml(t('bd.mana.variations'))}</div><ul>${variations}</ul>`
    : '';
  return `
    <details class="gf-mana-potential" title="${escapeAttr(t('bd.mana.potentialTitle'))}">
      <summary><span class="gf-mana-potential-label">${escapeHtml(t('bd.mana.maximum'))}</span><strong>${Number(potential.maximum || 0)}</strong></summary>
      <div class="gf-mana-potential-details">${details}</div>
    </details>`;
}
