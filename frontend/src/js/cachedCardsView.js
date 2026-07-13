// "Karten-Cache" tab: browse every card the backend has resolved so far
// (mtg_analyzer CardDatabase, see docs/Reference/08_CARD_CACHE_EXPORT_IMPORT.md).
// Lazy by design, matching the backend's own philosophy: nothing is
// fetched until this tab is actually opened, and re-opening it refreshes
// the list (new cards accumulate as decks get imported elsewhere).

import { listCachedCards } from './api.js';
import { renderCardTile } from './cardTile.js';

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

    resultEl.innerHTML = `<div class="card-tile-grid">${cards.map((c) => renderCardTile(c)).join('')}</div>`;
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
