// "Karten-Cache" tab: browse the cards the backend has resolved so far
// (mtg_analyzer CardDatabase, see docs/Reference/08_CARD_CACHE_EXPORT_IMPORT.md).
// A scope toggle picks between "Deck-Karten" (only cards referenced by a
// saved deck, GET /api/cards?scope=decks — the default, since it's the
// relevant subset for most users) and "Alle Karten" (the full cache,
// including the ~34k-card bulk Oracle import, scope=all).
//
// Lazy by design, matching the backend's own philosophy: nothing is
// fetched until this tab is actually opened, and re-opening it (or
// switching scope) refreshes the list.
//
// Filtering is entirely client-side over the already-fetched list — cheap
// for "Deck-Karten", but "Alle Karten" can be tens of thousands of cards;
// no server round trip per filter change either way.

import { listCachedCards } from './api.js';
import { renderCardTile } from './cardTile.js';
import { TYPE_BUCKETS } from './deckAnalysis.js';

const COLORS = [
  { key: 'W', label: '⚪ Weiß' },
  { key: 'U', label: '🔵 Blau' },
  { key: 'B', label: '⚫ Schwarz' },
  { key: 'R', label: '🔴 Rot' },
  { key: 'G', label: '🟢 Grün' },
  { key: 'C', label: '🔘 Farblos' },
];

// Mirrors the badges `cardTile.js`'s `renderCoverageBadge` shows (📖/✅/✖) —
// "catalogue" and "oracle" are both `coverage.modeled`, just a different
// `coverage.source` (see `api/cards.py`'s `_coverage_for`).
const COVERAGE_OPTIONS = [
  { key: 'catalogue', label: '📖 Katalogisiert' },
  { key: 'oracle', label: '✅ Modelliert' },
  { key: 'unmodeled', label: '✖ Nicht modelliert' },
];

function coverageKey(coverage) {
  if (!coverage) return 'unmodeled';
  if (coverage.source === 'catalogue') return 'catalogue';
  return coverage.modeled ? 'oracle' : 'unmodeled';
}

function checkedValues(root, filterName) {
  return Array.from(root.querySelectorAll(`input[data-filter="${filterName}"]:checked`)).map((el) => el.value);
}

function readFilterState(filtersEl) {
  const cmcMinRaw = filtersEl.querySelector('#cache-cmc-min').value;
  const cmcMaxRaw = filtersEl.querySelector('#cache-cmc-max').value;
  return {
    types: checkedValues(filtersEl, 'type'),
    coverage: checkedValues(filtersEl, 'coverage'),
    colors: checkedValues(filtersEl, 'color'),
    cmcMin: cmcMinRaw === '' ? null : Number(cmcMinRaw),
    cmcMax: cmcMaxRaw === '' ? null : Number(cmcMaxRaw),
  };
}

function cardMatchesFilters(card, filters) {
  if (!TYPE_BUCKETS.some((bucket) => filters.types.includes(bucket.key) && bucket.test(card))) return false;
  if (!filters.coverage.includes(coverageKey(card.coverage))) return false;

  const identity = card.color_identity || [];
  const colorMatch = identity.length === 0 ? filters.colors.includes('C') : identity.some((c) => filters.colors.includes(c));
  if (!colorMatch) return false;

  const cmc = card.converted_mana_cost ?? 0;
  if (filters.cmcMin != null && cmc < filters.cmcMin) return false;
  if (filters.cmcMax != null && cmc > filters.cmcMax) return false;

  return true;
}

function filterGroupHtml(legend, filterName, options) {
  return `
    <fieldset class="cache-filter-group">
      <legend>${legend}</legend>
      ${options
        .map(
          (o) =>
            `<label><input type="checkbox" data-filter="${filterName}" value="${o.key}" checked /> ${o.label}</label>`
        )
        .join('')}
    </fieldset>`;
}

export function renderCachedCardsView(container) {
  container.innerHTML = `
    <div class="cache-panel">
      <div class="cache-toolbar">
        <h2>Karten-Cache</h2>
        <div class="cache-scope-toggle" role="radiogroup" aria-label="Kartenumfang">
          <label><input type="radio" name="cache-scope" value="decks" checked /> Deck-Karten</label>
          <label><input type="radio" name="cache-scope" value="all" /> Alle Karten</label>
        </div>
        <button id="refresh-cache-btn" type="button">Aktualisieren</button>
        <span class="cache-count"></span>
      </div>
      <p class="cache-coverage-legend hint">
        Engine-Abdeckung je Karte (siehe „Engine-Status"-Tab für Details):
        📖 katalogisiert · ✅ vom Oracle-Parser modelliert · ✖ nicht modelliert
        (nur Keywords wirken, restlicher Text ist noch nicht spielbar).
      </p>
      <div class="cache-filters" id="cache-filters">
        ${filterGroupHtml('Kartentyp', 'type', TYPE_BUCKETS)}
        ${filterGroupHtml('Engine-Abdeckung', 'coverage', COVERAGE_OPTIONS)}
        ${filterGroupHtml('Farbe', 'color', COLORS)}
        <fieldset class="cache-filter-group">
          <legend>Manawert (CMC)</legend>
          <label>Min <input type="number" id="cache-cmc-min" min="0" step="1" placeholder="0" /></label>
          <label>Max <input type="number" id="cache-cmc-max" min="0" step="1" placeholder="∞" /></label>
        </fieldset>
        <button type="button" id="cache-filter-reset">Filter zurücksetzen</button>
      </div>
      <div id="cache-result"><p class="empty-state"><span class="spinner" aria-hidden="true"></span>Lade Karten-Cache …</p></div>
    </div>
  `;

  const resultEl = container.querySelector('#cache-result');
  const countEl = container.querySelector('.cache-count');
  const refreshBtn = container.querySelector('#refresh-cache-btn');
  const filtersEl = container.querySelector('#cache-filters');
  const resetBtn = container.querySelector('#cache-filter-reset');
  const scopeInputs = container.querySelectorAll('input[name="cache-scope"]');

  let allCards = [];

  function currentScope() {
    return container.querySelector('input[name="cache-scope"]:checked').value;
  }

  function renderFiltered() {
    if (!allCards.length) return;
    const filters = readFilterState(filtersEl);
    const filtered = allCards.filter((c) => cardMatchesFilters(c, filters));
    const modeledCount = filtered.filter((c) => c.coverage?.modeled).length;

    countEl.textContent =
      `${filtered.length} von ${allCards.length} Karte(n)` +
      (filtered.length ? ` · ${modeledCount} vollständig modelliert (${Math.round((modeledCount / filtered.length) * 100)} %)` : '');

    resultEl.innerHTML = filtered.length
      ? `<div class="card-tile-grid">${filtered.map((c) => renderCardTile(c)).join('')}</div>`
      : '<p class="empty-state">Keine Karten entsprechen den gewählten Filtern.</p>';
  }

  let latestRequestId = 0;

  async function load() {
    const requestId = ++latestRequestId;
    const scope = currentScope();
    resultEl.innerHTML = '<p class="empty-state"><span class="spinner" aria-hidden="true"></span>Lade Karten-Cache …</p>';
    countEl.textContent = '';

    const cards = await listCachedCards(scope);
    if (requestId !== latestRequestId) return; // superseded by a later refresh/scope change

    if (cards === null) {
      resultEl.innerHTML = '<p class="server-status warning">Server nicht erreichbar.</p>';
      return;
    }

    allCards = cards;

    if (!allCards.length) {
      countEl.textContent = '';
      resultEl.innerHTML = `<p class="empty-state">${
        scope === 'decks'
          ? 'Keine im Cache gespeicherten Deck-Karten – importiere oder öffne einen gespeicherten Deck.'
          : 'Noch keine Karten im Cache – importiere eine Deckliste, um welche zu laden.'
      }</p>`;
      return;
    }

    renderFiltered();
  }

  refreshBtn.addEventListener('click', load);
  scopeInputs.forEach((el) => el.addEventListener('change', load));
  filtersEl.addEventListener('change', renderFiltered);
  filtersEl.addEventListener('input', (e) => {
    if (e.target.matches('#cache-cmc-min, #cache-cmc-max')) renderFiltered();
  });
  resetBtn.addEventListener('click', () => {
    filtersEl.querySelectorAll('input[type="checkbox"]').forEach((el) => { el.checked = true; });
    filtersEl.querySelector('#cache-cmc-min').value = '';
    filtersEl.querySelector('#cache-cmc-max').value = '';
    renderFiltered();
  });

  // Only load the first time this view is shown, not eagerly at startup —
  // the tab may never be opened in a given session.
  let loaded = false;
  container.addEventListener('view-shown', () => {
    if (loaded) return;
    loaded = true;
    load();
  });
}
