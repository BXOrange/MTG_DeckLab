// "Gespeicherte Decks" tab: browse, load, and delete decks saved via
// POST /api/decks/save (mtg_analyzer DeckDatabase). Lazy by design, same
// as cachedCardsView.js: nothing is fetched until the tab is opened.
//
// The deck's author and sleeve are edited only in the "Deck editieren"
// tab (deckImportView.js) — this view only displays the author, matching
// the read-only treatment of colorIdentity/commanders here (both computed
// elsewhere too). Filtering (color/legality) is client-side over the
// already-fetched list, same pattern as cachedCardsView.js's filters.

import { listSavedDecks, getSavedDeck, deleteSavedDeck, getDeckValidation, getDeckCoverage, saveDeck, listArchetypes } from './api.js';
import { escapeHtml } from './cardTile.js';
import { t, tPlural, fmtDate } from './i18n.js';

// Archetype id -> label lookup (mtg_analyzer/data/archetypes.json via GET
// /api/archetypes), fetched once and cached module-wide — the same static,
// player-independent catalogue deckImportView.js's edit-mode picker uses.
// `null` means "not fetched yet"; a badge just renders the raw id in that
// narrow window rather than blocking the deck list on it.
let archetypeLabels = null;
async function ensureArchetypeLabels() {
  if (archetypeLabels) return archetypeLabels;
  const res = await listArchetypes();
  archetypeLabels = {};
  for (const entry of res.ok ? res.data || [] : []) {
    archetypeLabels[entry.id] = entry.label;
  }
  return archetypeLabels;
}

// Labels resolved at import — i18n initializes first, a language change
// reloads the page (see i18n.js). Colour glyphs stay inline.
const COLOR_GLYPHS = { W: '⚪', U: '🔵', B: '⚫', R: '🔴', G: '🟢', C: '🔘' };
const COLOR_FILTER_OPTIONS = ['W', 'U', 'B', 'R', 'G', 'C'].map((key) => ({
  key,
  label: `${COLOR_GLYPHS[key]} ${t(`common.color.${key}`)}`,
}));

const LEGALITY_FILTER_OPTIONS = [
  { key: 'legal', label: t('savedDecks.legality.legal') },
  { key: 'illegal', label: t('savedDecks.legality.illegal') },
  { key: 'unknown', label: t('savedDecks.legality.unknown') },
];

//: `isCube` (models/deck.py) marks a saved decklist as a card pool (e.g. a
//: curated "staples" reference list) rather than a real Commander deck —
//: no legality check runs for it (see the skipped fetch below).
const DECK_TYPE_FILTER_OPTIONS = [
  { key: 'deck', label: t('savedDecks.type.deck') },
  { key: 'cube', label: t('savedDecks.type.cube') },
];

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

function checkedValues(root, filterName) {
  return Array.from(root.querySelectorAll(`input[data-filter="${filterName}"]:checked`)).map((el) => el.value);
}

function readFilterState(filtersEl) {
  return {
    colors: checkedValues(filtersEl, 'color'),
    legality: checkedValues(filtersEl, 'legality'),
    deckType: checkedValues(filtersEl, 'deckType'),
  };
}

function deckMatchesColorFilter(colorIdentity, colors) {
  if (!colorIdentity) return true; // identity not computed yet — don't hide
  if (!colorIdentity.length) return colors.includes('C');
  return colorIdentity.some((c) => colors.includes(c));
}

function deckMatchesLegalityFilter(validation, legality) {
  if (validation === undefined || validation === null) return legality.includes('unknown');
  return legality.includes(validation.isLegal ? 'legal' : 'illegal');
}

function deckMatchesTypeFilter(isCube, deckType) {
  return deckType.includes(isCube ? 'cube' : 'deck');
}

/**
 * @param {{onLoadDeck?: (deck: object) => void, onAnalyzeDeck?: (deck: object) => void}} [options]
 *   onLoadDeck is called with the full saved deck (including decklist text)
 *   when "Deck editieren" is clicked; onAnalyzeDeck likewise for "Deck
 *   analysieren".
 */
export function renderSavedDecksView(container, { onLoadDeck, onAnalyzeDeck } = {}) {
  container.innerHTML = `
    <div class="saved-decks-panel">
      <div class="cache-toolbar">
        <h2>${t('savedDecks.title')}</h2>
        <button id="refresh-saved-decks-btn" type="button">${t('savedDecks.refresh')}</button>
        <span class="cache-count"></span>
      </div>
      <div class="cache-filters" id="saved-decks-filters">
        ${filterGroupHtml(t('savedDecks.filter.color'), 'color', COLOR_FILTER_OPTIONS)}
        ${filterGroupHtml(t('savedDecks.filter.legality'), 'legality', LEGALITY_FILTER_OPTIONS)}
        ${filterGroupHtml(t('savedDecks.filter.type'), 'deckType', DECK_TYPE_FILTER_OPTIONS)}
        <button type="button" id="saved-decks-filter-reset">${t('savedDecks.filter.reset')}</button>
      </div>
      <div id="saved-decks-result"><p class="empty-state"><span class="spinner" aria-hidden="true"></span>${t('savedDecks.loading')}</p></div>
    </div>
  `;

  const resultEl = container.querySelector('#saved-decks-result');
  const countEl = container.querySelector('.cache-count');
  const refreshBtn = container.querySelector('#refresh-saved-decks-btn');
  const filtersEl = container.querySelector('#saved-decks-filters');
  const resetBtn = container.querySelector('#saved-decks-filter-reset');

  // Kept across renders so applyFilters() (triggered by a filter checkbox,
  // not a reload) can look up each visible row's data without re-fetching.
  let currentDecks = [];
  // deckId -> validation result, or undefined while still checking. Reset
  // on every load() since a refresh may add/remove/change decks.
  const validationById = new Map();

  function applyFilters() {
    const filters = readFilterState(filtersEl);
    let visibleCount = 0;
    resultEl.querySelectorAll('.saved-deck-row').forEach((row) => {
      const deck = currentDecks.find((d) => d.id === row.dataset.deckId);
      const visible =
        deckMatchesColorFilter(deck?.colorIdentity, filters.colors) &&
        deckMatchesLegalityFilter(validationById.get(row.dataset.deckId), filters.legality) &&
        deckMatchesTypeFilter(deck?.isCube, filters.deckType);
      row.classList.toggle('saved-deck-row--hidden', !visible);
      if (visible) visibleCount += 1;
    });
    countEl.textContent =
      visibleCount === currentDecks.length
        ? tPlural('savedDecks.count', currentDecks.length)
        : t('savedDecks.countFiltered', { shown: visibleCount, total: currentDecks.length });
  }

  let latestRequestId = 0;

  async function load() {
    const requestId = ++latestRequestId;
    resultEl.innerHTML = `<p class="empty-state"><span class="spinner" aria-hidden="true"></span>${t('savedDecks.loading')}</p>`;
    countEl.textContent = '';

    const [decks] = await Promise.all([listSavedDecks(), ensureArchetypeLabels()]);
    if (requestId !== latestRequestId) return; // superseded by a later refresh click

    if (decks === null) {
      resultEl.innerHTML = `<p class="server-status warning">${t('common.serverUnreachable')}</p>`;
      return;
    }

    currentDecks = decks;
    validationById.clear();
    countEl.textContent = tPlural('savedDecks.count', decks.length);

    if (!decks.length) {
      resultEl.innerHTML = `<p class="empty-state">${t('savedDecks.empty')}</p>`;
      return;
    }

    resultEl.innerHTML = decks.map((deck) => renderDeckRow(deck)).join('');
    applyFilters();

    // Legality is computed server-side (resolves cards), so fetch it per
    // deck and fill each row's badge as answers arrive. Illegal decks get
    // a 🛑 + the reasons; legal ones a subtle ✅. Skipped for cube decks —
    // no Commander legality applies to a card pool (renderDeckRow shows a
    // 🧊 badge instead), so there's nothing meaningful to fetch/display.
    for (const deck of decks) {
      if (deck.isCube) continue;
      getDeckValidation(deck.id).then((validation) => {
        if (requestId !== latestRequestId) return; // list refreshed meanwhile
        validationById.set(deck.id, validation);
        updateLegalityBadge(deck.id, validation);
        applyFilters();
      });
    }

    // Engine-coverage note ("N Karten nicht modelliert") — a goldfishing
    // readiness hint, not a legality check, so it's fetched for cubes too.
    for (const deck of decks) {
      getDeckCoverage(deck.id).then((coverage) => {
        if (requestId !== latestRequestId) return; // list refreshed meanwhile
        updateCoverageBadge(deck.id, coverage);
      });
    }

    resultEl.querySelectorAll('.load-deck-btn').forEach((btn) => {
      btn.addEventListener('click', async () => {
        btn.disabled = true;
        const deck = await getSavedDeck(btn.dataset.deckId);
        btn.disabled = false;
        if (!deck) {
          window.alert(t('savedDecks.loadFailed'));
          return;
        }
        onLoadDeck?.(deck);
      });
    });

    resultEl.querySelectorAll('.analyze-deck-btn').forEach((btn) => {
      btn.addEventListener('click', async () => {
        btn.disabled = true;
        const deck = await getSavedDeck(btn.dataset.deckId);
        btn.disabled = false;
        if (!deck) {
          window.alert(t('savedDecks.loadFailed'));
          return;
        }
        onAnalyzeDeck?.(deck);
      });
    });

    // VIS-2: rename in place (same id, new name) and duplicate-as-new
    // (no id — the server generates a fresh one, same as a brand-new
    // save). Both go through the same `saveDeck` endpoint used for
    // saving edits; no dedicated backend route needed.
    resultEl.querySelectorAll('.rename-deck-btn').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const deck = decks.find((d) => d.id === btn.dataset.deckId);
        if (!deck) return;
        const currentName = btn.dataset.deckName || '';
        const newName = window.prompt(t('savedDecks.renamePrompt'), currentName);
        if (newName === null) return; // cancelled
        const trimmed = newName.trim();
        if (!trimmed || trimmed === currentName) return;
        btn.disabled = true;
        const saved = await saveDeck({ ...deck, name: trimmed });
        if (!saved) {
          btn.disabled = false;
          window.alert(t('savedDecks.renameFailed'));
          return;
        }
        load();
      });
    });

    resultEl.querySelectorAll('.duplicate-deck-btn').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const deck = decks.find((d) => d.id === btn.dataset.deckId);
        if (!deck) return;
        btn.disabled = true;
        const baseName = deck.name?.trim() || t('common.unnamedDeck');
        const saved = await saveDeck({ ...deck, id: null, name: t('savedDecks.copySuffix', { name: baseName }) });
        if (!saved) {
          btn.disabled = false;
          window.alert(t('savedDecks.duplicateFailed'));
          return;
        }
        load();
      });
    });

    resultEl.querySelectorAll('.delete-deck-btn').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const name = btn.dataset.deckName || t('savedDecks.deleteFallbackName');
        if (!window.confirm(t('savedDecks.deleteConfirm', { name }))) return;
        btn.disabled = true;
        const deleted = await deleteSavedDeck(btn.dataset.deckId);
        if (!deleted) {
          btn.disabled = false;
          window.alert(t('savedDecks.deleteFailed'));
          return;
        }
        load();
      });
    });
  }

  function updateLegalityBadge(deckId, validation) {
    const el = resultEl.querySelector(`.saved-deck-legality[data-deck-id="${cssEscape(deckId)}"]`);
    if (!el) return;
    if (validation === null) {
      el.className = 'saved-deck-legality unknown';
      el.textContent = t('savedDecks.legalityNotCheckable');
      el.removeAttribute('title');
      return;
    }
    if (validation.isLegal) {
      el.className = 'saved-deck-legality legal';
      el.textContent = t('savedDecks.legalityLegal');
      el.removeAttribute('title');
      return;
    }
    const reasons = (validation.errors || []).join('\n') || t('savedDecks.legalityIllegalDefault');
    el.className = 'saved-deck-legality illegal';
    el.textContent = t('savedDecks.legalityIllegal');
    el.title = reasons;
  }

  // Only rendered when there's something to report — a fully-modeled deck
  // (or a still-loading/unreachable coverage check) shows nothing here.
  function updateCoverageBadge(deckId, coverage) {
    const el = resultEl.querySelector(`.saved-deck-coverage[data-deck-id="${cssEscape(deckId)}"]`);
    if (!el || !coverage || !coverage.unmodeledCount) return;
    el.textContent = tPlural('savedDecks.coverageBadge', coverage.unmodeledCount);
    el.title = (coverage.unmodeledCardNames || []).join('\n');
  }

  refreshBtn.addEventListener('click', load);
  filtersEl.addEventListener('change', applyFilters);
  resetBtn.addEventListener('click', () => {
    filtersEl.querySelectorAll('input[type="checkbox"]').forEach((el) => { el.checked = true; });
    applyFilters();
  });

  // Only load the first time this view is shown, not eagerly at startup.
  let loaded = false;
  container.addEventListener('view-shown', () => {
    if (loaded) return;
    loaded = true;
    load();
  });
}

function renderDeckRow(deck) {
  const created = formatTimestamp(deck.createdAt);
  const name = deck.name?.trim() || t('common.unnamedDeck');

  return `
    <div class="saved-deck-row" data-deck-id="${escapeHtml(deck.id)}">
      <div class="saved-deck-info">
        <strong>${escapeHtml(name)}</strong>
        ${cubeHtml(deck.isCube)}
        ${commanderHtml(deck.commanders)}
        ${authorHtml(deck.author)}
        ${archetypeHtml(deck.archetypes)}
        <span class="saved-deck-meta">${escapeHtml(t('savedDecks.savedAt', { date: created }))}${colorIdentityHtml(deck.colorIdentity)}</span>
        ${deck.isCube
          ? `<span class="saved-deck-legality cube">${t('savedDecks.cubeNoLegality')}</span>`
          : `<span class="saved-deck-legality checking" data-deck-id="${escapeHtml(deck.id)}">${t('savedDecks.checkingLegality')}</span>`}
        <span class="saved-deck-coverage" data-deck-id="${escapeHtml(deck.id)}"></span>
      </div>
      <div class="saved-deck-actions">
        <div class="saved-deck-actions-row">
          <button type="button" class="load-deck-btn" data-deck-id="${deck.id}">${t('savedDecks.editDeck')}</button>
          <button type="button" class="analyze-deck-btn" data-deck-id="${deck.id}">${t('savedDecks.analyzeDeck')}</button>
        </div>
        <div class="saved-deck-actions-row">
          <button type="button" class="rename-deck-btn" data-deck-id="${deck.id}" data-deck-name="${escapeHtml(name)}">${t('savedDecks.rename')}</button>
          <button type="button" class="duplicate-deck-btn" data-deck-id="${deck.id}">${t('savedDecks.duplicate')}</button>
          <button type="button" class="delete-deck-btn" data-deck-id="${deck.id}" data-deck-name="${escapeHtml(name)}">${t('common.delete')}</button>
        </div>
      </div>
    </div>
  `;
}

//: WUBRG mana symbol → CSS class + label, in canonical color order.
const COLOR_PIPS = [
  { code: 'W', className: 'w', label: t('common.color.W') },
  { code: 'U', className: 'u', label: t('common.color.U') },
  { code: 'B', className: 'b', label: t('common.color.B') },
  { code: 'R', className: 'r', label: t('common.color.R') },
  { code: 'G', className: 'g', label: t('common.color.G') },
];

// The commander line under a saved deck's name (Commander decks only;
// `commanders` is [] for a deck with no commander section, or `null`/
// `undefined` for one whose identity hasn't been computed yet — both
// render nothing here).
function commanderHtml(commanders) {
  if (!commanders || !commanders.length) return '';
  return `<span class="saved-deck-commander">👑 ${escapeHtml(commanders.join(' & '))}</span>`;
}

// Cube badge, shown read-only here — editable only in "Deck editieren"
// (deckImportView.js), same treatment as author/sleeve.
function cubeHtml(isCube) {
  if (!isCube) return '';
  return `<span class="saved-deck-cube-badge" title="${escapeHtml(t('savedDecks.cubeBadgeTitle'))}">🧊 Collection</span>`;
}

// The author, shown read-only here — editable only in "Deck editieren"
// (deckImportView.js). Renders nothing when unset (may be empty/None).
function authorHtml(author) {
  if (!author) return '';
  return `<span class="saved-deck-author">✍️ ${escapeHtml(author)}</span>`;
}

// The deck's archetype tags, shown read-only here — editable only in
// "Deck editieren". Falls back to the raw id if the label lookup hasn't
// resolved yet (see `ensureArchetypeLabels`) rather than rendering nothing.
function archetypeHtml(archetypes) {
  if (!archetypes || !archetypes.length) return '';
  const labels = archetypes.map((id) => (archetypeLabels && archetypeLabels[id]) || id);
  return `<span class="saved-deck-archetypes">🎭 ${escapeHtml(labels.join(' · '))}</span>`;
}

// Color-identity pips (WUBRG order), or a colorless "C" pip for an empty
// (but computed) identity. Renders nothing while uncomputed (`null`).
function colorIdentityHtml(colorIdentity) {
  if (!colorIdentity) return '';
  if (!colorIdentity.length) {
    return ` · <span class="color-identity"><span class="color-pip color-pip--c" title="${escapeHtml(t('common.color.C'))}">C</span></span>`;
  }
  const set = new Set(colorIdentity);
  const pips = COLOR_PIPS.filter((p) => set.has(p.code))
    .map((p) => `<span class="color-pip color-pip--${p.className}" title="${p.label}">${p.code}</span>`)
    .join('');
  return ` · <span class="color-identity">${pips}</span>`;
}

// Deck ids are server-generated UUIDs (no quotes/backslashes), so a
// minimal escape is enough for the attribute selector above.
function cssEscape(value) {
  return String(value).replace(/["\\]/g, '\\$&');
}

function formatTimestamp(isoString) {
  const date = new Date(isoString);
  return Number.isNaN(date.getTime()) ? isoString : fmtDate(date);
}
