// "Karten-Cache" tab: browse every card the backend has resolved so far
// (mtg_analyzer CardDatabase, see docs/08_CARD_CACHE_EXPORT_IMPORT.md).
// Lazy by design, matching the backend's own philosophy: nothing is
// fetched until this tab is actually opened, and re-opening it refreshes
// the list (new cards accumulate as decks get imported elsewhere).

import { listCachedCards, cardImageUrl } from './api.js';

export function renderCachedCardsView(container) {
  container.innerHTML = `
    <div class="cache-panel">
      <div class="cache-toolbar">
        <h2>Karten-Cache</h2>
        <button id="refresh-cache-btn" type="button">Aktualisieren</button>
        <span class="cache-count"></span>
      </div>
      <div id="cache-result"><p class="empty-state">Lade Karten-Cache …</p></div>
    </div>
  `;

  const resultEl = container.querySelector('#cache-result');
  const countEl = container.querySelector('.cache-count');
  const refreshBtn = container.querySelector('#refresh-cache-btn');

  let latestRequestId = 0;

  async function load() {
    const requestId = ++latestRequestId;
    resultEl.innerHTML = '<p class="empty-state">Lade Karten-Cache …</p>';
    countEl.textContent = '';

    const cards = await listCachedCards();
    if (requestId !== latestRequestId) return; // superseded by a later refresh click

    if (cards === null) {
      resultEl.innerHTML = '<p class="server-status warning">Server nicht erreichbar.</p>';
      return;
    }

    countEl.textContent = `${cards.length} Karte(n) im Cache`;

    if (!cards.length) {
      resultEl.innerHTML =
        '<p class="empty-state">Noch keine Karten im Cache – importiere eine Deckliste, um welche zu laden.</p>';
      return;
    }

    resultEl.innerHTML = `<div class="card-cache-grid">${cards.map(renderCacheCard).join('')}</div>`;
  }

  refreshBtn.addEventListener('click', load);

  // Only load the first time this view is shown, not eagerly at startup —
  // the tab may never be opened in a given session.
  let loaded = false;
  container.addEventListener('view-shown', () => {
    if (loaded) return;
    loaded = true;
    load();
  });
}

// Colored mana symbols get a matching colored circle; {C} (the specific
// colorless-mana symbol, distinct from generic cost) gets a neutral one.
const MANA_SYMBOL_EMOJI = { W: '⚪', U: '🔵', B: '⚫', R: '🔴', G: '🟢', C: '🔘' };

// Keycap digit emojis, indexed by digit — used to spell out generic mana
// (e.g. 12 -> "1️⃣2️⃣") one character at a time, so any amount works without
// a lookup table per number.
const DIGIT_EMOJI = ['0️⃣', '1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣', '6️⃣', '7️⃣', '8️⃣', '9️⃣'];

function genericManaEmoji(amount) {
  return String(amount)
    .split('')
    .map((digit) => DIGIT_EMOJI[Number(digit)])
    .join('');
}

// Card.mana_cost (from the backend) only counts colored/colorless pips
// ({W}, {U}, ..., {C}) — generic numeric mana ({2}, {10}, ...) isn't
// stored per-symbol since it doesn't fit that shape. It's derived here
// instead: a card's mana value counts every symbol as 1 (including
// hybrid/Phyrexian ones), so subtracting the pips we do know about
// leaves the generic amount for the vast majority of real costs.
function renderManaCost(card) {
  const pips = card.mana_cost || {};
  const pipTotal = Object.values(pips).reduce((sum, count) => sum + count, 0);
  const generic = Math.max(0, (card.converted_mana_cost || 0) - pipTotal);

  const parts = [];
  if (generic > 0) parts.push(genericManaEmoji(generic));
  for (const symbol of ['C', 'W', 'U', 'B', 'R', 'G']) {
    const count = pips[symbol] || 0;
    if (count > 0) parts.push(MANA_SYMBOL_EMOJI[symbol].repeat(count));
  }
  return parts.join(' ');
}

function renderCacheCard(card) {
  const manaCost = renderManaCost(card);
  const powerToughness = card.power != null && card.toughness != null ? `${card.power}/${card.toughness}` : '';

  const metaParts = [card.rarity, card.set_code ? card.set_code.toUpperCase() : ''].filter(Boolean);

  return `
    <div class="cache-card">
      <img src="${cardImageUrl(card.id, 'normal')}" alt="${escapeHtml(card.name)}" loading="lazy" />
      <div class="cache-card-info">
        <h4>${escapeHtml(card.name)}</h4>
        <p class="cache-card-type">${escapeHtml(card.type_line)}</p>
        ${manaCost ? `<p class="cache-card-cost">${manaCost}</p>` : ''}
        ${powerToughness ? `<p class="cache-card-pt">${escapeHtml(powerToughness)}</p>` : ''}
        ${card.oracle_text ? `<p class="cache-card-text">${escapeHtml(card.oracle_text)}</p>` : ''}
        ${card.keywords?.length ? `<p class="cache-card-keywords">${escapeHtml(card.keywords.join(', '))}</p>` : ''}
        ${metaParts.length ? `<p class="cache-card-meta">${escapeHtml(metaParts.join(' · '))}</p>` : ''}
      </div>
    </div>
  `;
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}
