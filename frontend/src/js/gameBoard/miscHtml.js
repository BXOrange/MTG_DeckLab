// Small pure HTML/label helpers (zones, restricted mana, cost reductions, popover placement).

import { getShowOpponentHand } from '../settings.js';
import { restrictionLabel } from './cardHints.js';
import { t } from '../i18n.js';
import { escapeHtml, escapeAttr } from './html.js';

// Only rendered on a hand that isn't yours (see `ownHand`) — in
// Replay/Puzzle mode both boards are yours to edit, so there is nothing
// to hide and no toggle.
export function opponentHandToggleHtml() {
  return `
    <label class="gf-bf-toggle gf-hand-toggle" title="${escapeAttr(t('bd.hand.showOppTitle'))}">
      <input type="checkbox" class="gf-opp-hand-toggle" ${getShowOpponentHand() ? 'checked' : ''} />
      ${t('bd.hand.showOppShort')}
    </label>`;
}

export function zoneListHtml(objs, empty) {
  if (!objs.length) return `<p class="empty-state">${empty}</p>`;
  return `<ul class="gf-zone-list">${objs
    .map((o) => `<li data-hover-card="${escapeHtml(o.name)}">${escapeHtml(o.name)}</li>`)
    .join('')}</ul>`;
}

// RULE 605.3a: mana tagged "spend only on X" (`ManaPool.to_dict`'s additive
// `restricted` key — a list of lots, never merged with the ordinary WUBRGC
// counts above) shown as its own badge per lot, so a player can tell
// restricted floating mana apart from ordinary mana instead of it just
// silently failing to pay an unrelated cost later.
export function restrictedManaHtml(restricted, glyph, order) {
  if (!restricted || !restricted.length) return [];
  return restricted.map((lot) => {
    const amounts = order
      .filter((c) => c !== 'C' && lot.amounts[c] > 0)
      .concat(lot.amounts.C > 0 ? ['C'] : [])
      .map((c) => `${glyph[c]}${lot.amounts[c]}`)
      .join('');
    return `<span class="gf-mana gf-mana-restricted" title="${escapeAttr(t('bd.mana.restrictedTitle', { label: restrictionLabel(lot.restriction) }))}">🔒${amounts}</span>`;
  });
}

export function collectCostReductions(actions) {
  return actions
    .filter((a) => a.type === 'cast_spell' && a.base_cost && a.effective_cost && a.base_cost !== a.effective_cost)
    .map((a) => ({ name: a.name, base: a.base_cost, effective: a.effective_cost }));
}

// Anchor each per-card effect popover (top layer) at its Σ-badge when it
// opens — the top layer otherwise centres it — flipping above / clamping to
// the viewport so it never spills off-screen.
export function positionEffectPopover(pop, badge) {
  const r = badge.getBoundingClientRect();
  const pw = pop.offsetWidth;
  const ph = pop.offsetHeight;
  const margin = 8;
  let left = Math.min(r.left, window.innerWidth - pw - margin);
  left = Math.max(margin, left);
  let top = r.bottom + 4;
  if (top + ph > window.innerHeight - margin) top = r.top - ph - 4; // flip above
  top = Math.max(margin, top);
  pop.style.left = `${left}px`;
  pop.style.top = `${top}px`;
}

export function measurementValue(text, pending) {
  if (!/^\d+$/.test(text)) return null;
  const value = Number(text);
  const maximum = Number.isSafeInteger(pending.maximum) && pending.maximum >= 0
    ? Math.min(pending.maximum, Number.MAX_SAFE_INTEGER) : Number.MAX_SAFE_INTEGER;
  return Number.isSafeInteger(value) && value >= 0 && value <= maximum ? String(value) : null;
}

// A stable identity for one `order_triggers` option, for matching the
// same trigger across rounds despite its `id` being re-numbered each time
// (see `triggerOrderDraft` above). Source name + ability text is what a
// player actually distinguishes triggers by, so two genuinely
// indistinguishable triggers (same source, same text) are — correctly —
// not told apart here either.
export function triggerOptionKey(opt) {
  return `${opt.source_name || ''}␟${opt.label || opt.id}`;
}
