// Paginated card-cache browser. Coverage counts become available while the
// server prepares missing verdicts in the background.
import { getAuth, subscribeAuth } from './auth.js';
import { browseCachedCards } from './api.js';
import { renderCardTile } from './cardTile.js';
import { TYPE_BUCKETS } from './deckAnalysis.js';
import { t } from './i18n.js';

const PAGE_SIZE = 60;
const COVERAGE_POLL_MS = 2500;
const CMC_DEBOUNCE_MS = 250;

// Labels are resolved at import (i18n initializes first, and a language
// change reloads the page — see i18n.js), so a plain module-level array is
// fine. Colour glyphs stay inline; only the name is translated.
const COLOR_GLYPHS = { W: '⚪', U: '🔵', B: '⚫', R: '🔴', G: '🟢', C: '🔘' };
const COLORS = ['W', 'U', 'B', 'R', 'G', 'C'].map((key) => ({
  key,
  label: `${COLOR_GLYPHS[key]} ${t(`common.color.${key}`)}`,
}));

// Mirrors the badges `cardTile.js`'s `renderCoverageBadge` shows (📖/✅/✖) —
// "catalogue" and "oracle" are both `coverage.modeled`, just a different
// `coverage.source` (see `api/cards.py`'s `coverage_for`).
const COVERAGE_OPTIONS = [
  { key: 'catalogue', label: t('cache.coverage.catalogue') },
  { key: 'oracle', label: t('cache.coverage.oracle') },
  { key: 'unmodeled', label: t('cache.coverage.unmodeled') },
  { key: 'unsupported', label: t('cache.coverage.unsupported') },
];

function filterParams(filtersEl) {
  const params = new URLSearchParams();
  for (const [name, filter] of [['types', 'type'], ['coverage', 'coverage'], ['colors', 'color']]) {
    const inputs = [...filtersEl.querySelectorAll(`input[data-filter="${filter}"]`)];
    const selected = inputs.filter((el) => el.checked);
    // The explicit type list preserves the view's treatment of other card types.
    if (name === 'types' || selected.length !== inputs.length) {
      params.set(name, selected.map((el) => el.value).join(','));
    }
  }
  for (const [name, id] of [['cmc_min', '#cache-cmc-min'], ['cmc_max', '#cache-cmc-max']]) {
    const { value } = filtersEl.querySelector(id);
    if (value !== '') params.set(name, value);
  }
  return params;
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
        <h2>${t('cache.title')}</h2>
        <div class="cache-scope-toggle" role="radiogroup" aria-label="${t('cache.scopeAria')}">
          <label><input type="radio" name="cache-scope" value="decks" checked /> ${t('cache.scopeDecks')}</label>
          <label><input type="radio" name="cache-scope" value="all" /> ${t('cache.scopeAll')}</label>
        </div>
        <button id="refresh-cache-btn" type="button">${t('cache.refresh')}</button>
        <span class="cache-count"></span>
      </div>
      <p class="cache-coverage-legend hint">${t('cache.coverageLegend')}</p>
      <div class="cache-filters" id="cache-filters">
        ${filterGroupHtml(t('cache.filter.type'), 'type', TYPE_BUCKETS)}
        ${filterGroupHtml(t('cache.filter.coverage'), 'coverage', COVERAGE_OPTIONS)}
        ${filterGroupHtml(t('cache.filter.color'), 'color', COLORS)}
        <fieldset class="cache-filter-group">
          <legend>${t('cache.filter.cmc')}</legend>
          <label>${t('cache.filter.min')} <input type="number" id="cache-cmc-min" min="0" step="1" placeholder="0" /></label>
          <label>${t('cache.filter.max')} <input type="number" id="cache-cmc-max" min="0" step="1" placeholder="∞" /></label>
        </fieldset>
        <button type="button" id="cache-filter-reset">${t('cache.filter.reset')}</button>
      </div>
      <p class="hint" id="cache-coverage-status" role="status" hidden></p>
      <div class="cache-toolbar" id="cache-pagination" hidden>
        <button type="button" id="cache-prev">${t('cache.previous')}</button>
        <span id="cache-page"></span>
        <button type="button" id="cache-next">${t('cache.next')}</button>
      </div>
      <div id="cache-result"><p class="empty-state"><span class="spinner" aria-hidden="true"></span>${t('cache.loading')}</p></div>
    </div>
  `;

  const resultEl = container.querySelector('#cache-result');
  const countEl = container.querySelector('.cache-count');
  const refreshBtn = container.querySelector('#refresh-cache-btn');
  const filtersEl = container.querySelector('#cache-filters');
  const resetBtn = container.querySelector('#cache-filter-reset');
  const scopeInputs = container.querySelectorAll('input[name="cache-scope"]');

  const coverageStatus = container.querySelector('#cache-coverage-status');
  const pagination = container.querySelector('#cache-pagination');
  const pageLabel = container.querySelector('#cache-page');
  const previous = container.querySelector('#cache-prev');
  const next = container.querySelector('#cache-next');
  let offset = 0;
  let pollTimer;
  let filterTimer;
  let request;

  async function load({ poll = false } = {}) {
    clearTimeout(pollTimer);
    request?.abort();
    const current = new AbortController();
    request = current;
    const scope = container.querySelector('input[name="cache-scope"]:checked').value;
    const params = filterParams(filtersEl);
    params.set('scope', scope);
    params.set('offset', offset);
    params.set('limit', PAGE_SIZE);

    if (!poll) {
      resultEl.innerHTML = `<p class="empty-state"><span class="spinner" aria-hidden="true"></span>${t('cache.loading')}</p>`;
      countEl.textContent = '';
      coverageStatus.hidden = true;
      pagination.hidden = true;
    }

    const result = await browseCachedCards(params, current.signal);
    if (current.signal.aborted) return;
    if (!result) {
      if (poll) {
        pollTimer = setTimeout(() => load({ poll: true }), COVERAGE_POLL_MS);
        return;
      }
      resultEl.innerHTML = `<p class="server-status warning">${t('common.serverUnreachable')}</p>`;
      return;
    }

    const { cards, total, matched, modeled, pending } = result;
    if (matched && offset >= matched) {
      offset = Math.floor((matched - 1) / PAGE_SIZE) * PAGE_SIZE;
      await load();
      return;
    }
    countEl.textContent = matched == null ? '' : t('cache.count', { shown: matched, total });
    if (modeled != null && matched) {
      countEl.textContent += t('cache.modeledPart', { count: modeled, pct: Math.round(modeled / matched * 100) });
    }
    coverageStatus.textContent = pending ? t('cache.preparingCoverage') : '';
    coverageStatus.hidden = !pending;

    // A poll can update counts without replacing the visible images and tiles.
    if (!poll || !cards.length || !resultEl.querySelector('.card-tile-grid')) {
      const emptyMessage = !total ? (scope === 'decks' ? 'cache.emptyDecks' : 'cache.emptyAll') : 'cache.noMatch';
      resultEl.innerHTML = cards.length
        ? `<div class="card-tile-grid">${cards.map((card) => renderCardTile(card)).join('')}</div>`
        : matched == null ? '' : `<p class="empty-state">${t(emptyMessage)}</p>`;
    }

    pagination.hidden = !(matched > PAGE_SIZE);
    previous.disabled = offset === 0;
    next.disabled = offset + PAGE_SIZE >= matched;
    pageLabel.textContent = t('cache.page', { page: offset / PAGE_SIZE + 1, pages: Math.ceil(matched / PAGE_SIZE) });
    if (pending) pollTimer = setTimeout(() => load({ poll: true }), COVERAGE_POLL_MS);
  }

  function firstPage() {
    clearTimeout(filterTimer);
    offset = 0;
    load();
  }

  previous.addEventListener('click', () => { offset -= PAGE_SIZE; load(); });
  next.addEventListener('click', () => { offset += PAGE_SIZE; load(); });
  refreshBtn.addEventListener('click', firstPage);
  scopeInputs.forEach((el) => el.addEventListener('change', firstPage));
  filtersEl.addEventListener('change', (event) => {
    if (event.target.type === 'checkbox') firstPage();
  });
  filtersEl.addEventListener('input', (event) => {
    if (event.target.type !== 'number') return;
    clearTimeout(filterTimer);
    clearTimeout(pollTimer);
    request?.abort();
    filterTimer = setTimeout(firstPage, CMC_DEBOUNCE_MS);
  });
  resetBtn.addEventListener('click', () => {
    filtersEl.querySelectorAll('input[type="checkbox"]').forEach((el) => { el.checked = true; });
    filtersEl.querySelector('#cache-cmc-min').value = '';
    filtersEl.querySelector('#cache-cmc-max').value = '';
    firstPage();
  });

  // Only load the first time this view is shown, not eagerly at startup —
  // the tab may never be opened in a given session.
  let loaded = false;
  let accountId = getAuth().player_uuid;
  subscribeAuth((auth) => {
    if (accountId === auth.player_uuid) return;
    accountId = auth.player_uuid;
    if (loaded && scopeInputs[0].checked) firstPage();
  });
  container.addEventListener('view-shown', () => {
    if (loaded) return;
    loaded = true;
    load();
  });
}
