// "Deck analysieren" tab: once a deck is loaded, its analysis is split
// into four sub-tabs under the deck title/commander line — Statische
// Analyse (mana curve, card types, mana value, opening-hand land odds,
// color pips vs. sources, functional categories), Dynamische Analyse,
// Bracket-Analyse, and Advice (mana-curve guidance plus related Spellbook
// variants).
// Sub-tab switching (`wireAnalyzeTabs`) is a local, ad hoc show/hide of
// `.analyze-subtab-panel` elements — separate from and not reusing the
// app-level `.tab-button`/`.view` mechanism in app.js, which only knows
// about the top-level sidebar tabs.
//
// Opened from "Decks verwalten" (savedDecksView.js)'s "Deck analysieren"
// button, mirroring how "Deck editieren" hands a saved deck to
// deckImportView.js's loadDeck(). Most statistics are computed client-side
// from already-resolved card data (deckAnalysis.js); Commander Spellbook
// combo matching is fetched lazily from the backend when this analysis opens.

import { parseDeckSections } from './parser.js';
import { resolveCardImages } from './cardImages.js';
import { analyzeDeck } from './deckAnalysis.js';
import { analyzeManaAdvice } from './manaAdvice.js';
import { manaAdviceHtml, wireManaAdviceControls } from './manaAdviceView.js';
import { escapeHtml } from './cardTile.js';
import { renderDynamicAnalysisPanel } from './dynamicAnalysisPanel.js';
import {
  analyzeArchetypes,
  findDeckCombos,
  listSavedDecks,
  listFavoriteDecks,
} from './api.js';
import { getPlayerName } from './settings.js';
import { t, tPlural, fmtNumber } from './i18n.js';


function escapeAttr(str) {
  return String(str).replace(/'/g, '&#39;').replace(/"/g, '&quot;');
}

// A card name wired to `data-hover-card`, so the same hover-detail popup
// used in Goldfisch/Puzzle-Modus (cardHoverDetail.js, one global listener
// initialized once in app.js — any element with this attribute opts in)
// pops up here too, no per-view wiring needed.
function cardNameHtml(name, qty = 1) {
  return `<span class="analyze-card-name" data-hover-card="${escapeHtml(name)}">${escapeHtml(name)}</span>${qty > 1 ? ` ×${qty}` : ''}`;
}

const COLOR_NAMES = { W: t('common.color.W'), U: t('common.color.U'), B: t('common.color.B'), R: t('common.color.R'), G: t('common.color.G') };
const COLOR_CLASS = { W: 'w', U: 'u', B: 'b', R: 'r', G: 'g' };

// Frank Karsten's Commander model (TCGplayer, updated 2025-08-28):
// expected 99-card curve by commander's mana value; rocks and lands are
// separate from the 1–6 MV spell counts.
const COMMANDER_CURVE_REFERENCE = {
  2: { curve: [9, 0, 20, 14, 9, 4], rocks: 1, lands: 42 },
  3: { curve: [8, 19, 0, 16, 10, 3], rocks: 1, lands: 42 },
  4: { curve: [6, 12, 13, 0, 13, 8], rocks: 8, lands: 39 },
  5: { curve: [6, 12, 10, 13, 0, 10], rocks: 9, lands: 39 },
  6: { curve: [6, 12, 10, 14, 9, 0], rocks: 10, lands: 38 },
};
const GUIDE_BASE_LANDS = 42;
const GUIDE_BASE_MANA_ROCKS = 1;
const GUIDE_MIN_MIDRANGE_LANDS = 37;
const GUIDE_ROCKS_PER_LAND_CUT = { min: 2, max: 3 };

/**
 * @returns {{loadDeck: (savedDeck: object) => void, onShown: () => void}}
 *   lets savedDecksView.js hand a saved deck over (id/name/commanderText/
 *   mainboardText) when its "Deck analysieren" button is clicked; `onShown`
 *   lazy-loads the deck picker (own dropdown, see `deckPickerHtml` below)
 *   the first time this tab is actually opened.
 */
export function renderAnalyzeView(container) {
  let requestId = 0;

  // Deck picker state (own dropdown, mirroring goldfishView.js's start-panel
  // picker) — lets this page pick a deck directly instead of only being
  // reachable via "Decks verwalten"'s "Deck analysieren" button.
  let savedDecks = null; // null = not loaded yet
  let decksLoading = false;
  // VIS-1: distinct from "loaded, zero decks" — without this a network
  // failure silently rendered as "— keine gespeicherten Decks —" with no
  // indication anything went wrong (and no retry short of leaving the tab).
  let decksLoadError = false;
  let favoriteDeckIds = new Set();
  let currentDeckId = ''; // id of the deck currently shown/loading, '' if none

  container.innerHTML = emptyShellHtml();
  wireDeckPicker();
  wireAdviceCurveView(container);
  const restoreManaAdviceControls = wireManaAdviceControls(container);

  async function loadDecks() {
    decksLoading = true;
    updatePickerUI();
    const playerName = getPlayerName();
    const [decks, favorites] = await Promise.all([
      listSavedDecks(),
      playerName ? listFavoriteDecks(playerName) : Promise.resolve([]),
    ]);
    decksLoading = false;
    decksLoadError = decks === null;
    savedDecks = decks || [];
    favoriteDeckIds = new Set(favorites || []);
    updatePickerUI();
  }

  function onShown() {
    if (savedDecks === null || decksLoadError) loadDecks();
  }

  // Favorites (Profil tab) first, alphabetical order preserved within each
  // group — matches goldfishView.js's `decksFavoritesFirst`.
  function decksFavoritesFirst() {
    if (!savedDecks) return [];
    return [...savedDecks].sort(
      (a, b) => (favoriteDeckIds.has(b.id) ? 1 : 0) - (favoriteDeckIds.has(a.id) ? 1 : 0)
    );
  }

  function deckPickerOptionsHtml() {
    if (decksLoading && savedDecks === null) return `<option>${t('an.picker.loading')}</option>`;
    if (decksLoadError) return `<option value="">${t('an.picker.unreachable')}</option>`;
    if (!savedDecks || !savedDecks.length) {
      return `<option value="">${t('an.picker.none')}</option>`;
    }
    const options = [`<option value="">${t('an.picker.choose')}</option>`];
    for (const d of decksFavoritesFirst()) {
      const name = (d.name || '').trim() || t('common.unnamedDeck');
      const label = favoriteDeckIds.has(d.id) ? `★ ${name}` : name;
      const selected = d.id === currentDeckId ? ' selected' : '';
      options.push(`<option value="${escapeHtml(d.id)}"${selected}>${escapeHtml(label)}</option>`);
    }
    return options.join('');
  }

  function deckPickerHtml() {
    return `
      <div class="gf-deck-picker">
        <label for="analyze-deck-select">${t('an.deckLabel')}</label>
        <select id="analyze-deck-select" ${decksLoading ? 'disabled' : ''}>${deckPickerOptionsHtml()}</select>
        <button id="analyze-deck-refresh" type="button" title="${escapeAttr(t('an.reloadDecks'))}">⟳</button>
      </div>
    `;
  }

  // Called once right after every full `container.innerHTML` swap (the
  // select element itself is destroyed each time, so listeners don't
  // survive) — a plain `<select>`, not part of the `.analyze-subtab`
  // show/hide mechanism, since it must stay visible across every state.
  function wireDeckPicker() {
    const select = container.querySelector('#analyze-deck-select');
    select?.addEventListener('change', (e) => {
      const deckId = e.target.value;
      if (!deckId) return;
      const deck = savedDecks?.find((d) => d.id === deckId);
      if (deck) loadDeck(deck);
    });
    container.querySelector('#analyze-deck-refresh')?.addEventListener('click', loadDecks);
  }

  // Refreshes just the picker's options in place (no full re-render), so a
  // deck-list reload never wipes an already-displayed analysis.
  function updatePickerUI() {
    const select = container.querySelector('#analyze-deck-select');
    if (!select) return;
    select.innerHTML = deckPickerOptionsHtml();
    select.disabled = decksLoading;
  }

  function loadDeck(savedDeck) {
    const myRequestId = ++requestId;
    currentDeckId = savedDeck.id || '';
    container.innerHTML = loadingShellHtml(savedDeck.name);
    wireDeckPicker();

    const parsed = parseDeckSections({
      commanderText: savedDeck.commanderText,
      mainboardText: savedDeck.mainboardText,
    });
    const names = [...parsed.commanders, ...parsed.mainDeck].map((c) => c.name);

    resolveCardImages(names).then((resolved) => {
      if (myRequestId !== requestId) return; // superseded by a later loadDeck() call
      const stats = analyzeDeck(parsed.commanders, parsed.mainDeck, resolved);
      stats.manaAdvice = analyzeManaAdvice(parsed, resolved);
      const comboState = stats.unresolvedNames.length ? 'incomplete' : 'loading';
      container.innerHTML = resultShellHtml(savedDeck.name, stats, deckPickerHtml(), comboState);
      wireDeckPicker();
      wireAnalyzeTabs(container);
      restoreManaAdviceControls();

      const deckSource = savedDeck.id
        ? { deckId: savedDeck.id }
        : {
            commanderText: savedDeck.commanderText,
            mainboardText: savedDeck.mainboardText,
            sideboardText: savedDeck.sideboardText,
          };

      // ANA-4: mounted post-innerHTML like `wireAnalyzeTabs` above — the
      // panel wires its own live DOM listeners/polling, which a plain HTML
      // string builder (`resultShellHtml`) can't do.
      const simRoot = container.querySelector('#analyze-simulation-root');
      if (simRoot) {
        const dynamicPanel = renderDynamicAnalysisPanel(
          simRoot,
          {
            commanderText: savedDeck.commanderText,
            mainboardText: savedDeck.mainboardText,
            sideboardText: savedDeck.sideboardText,
            favoriteCards: savedDeck.favoriteCards || [],
          },
          stats.expectedManaCurve,
          comboState === 'loading' ? 'loading' : 'incomplete'
        );
        if (comboState !== 'loading') dynamicPanel.setCombos([], 'incomplete');
        if (comboState === 'loading') {
          loadComboAnalysis(savedDeck, parsed, resolved, myRequestId, stats, dynamicPanel.setCombos);
        }
      }

      // Playstyle/archetype suggestions come from the backend
      // (POST /api/archetypes/analyze — the catalogue + scoring both live
      // server-side, see api/archetypes.py) rather than being computed
      // here like the rest of the static tab, so it's a one-shot async
      // fetch into a placeholder rather than part of `stats`.
      const playstyleRoot = container.querySelector('#toc-playstyle-content');
      if (playstyleRoot) loadArchetypeSuggestions(playstyleRoot, deckSource, myRequestId);

    });
  }

  function loadComboAnalysis(savedDeck, parsed, resolved, myRequestId, initialStats, setDynamicCombos) {
    const cards = [...parsed.commanders, ...parsed.mainDeck]
      .map((entry) => {
        const card = resolved.get(entry.name.trim().toLowerCase())?.card;
        return card ? { name: card.name, quantity: entry.qty } : null;
      })
      .filter(Boolean);
    const identityEntries = parsed.commanders.length ? parsed.commanders : parsed.mainDeck;
    const colorIdentity = [...new Set(identityEntries.flatMap((entry) =>
      resolved.get(entry.name.trim().toLowerCase())?.card?.color_identity || []
    ))];
    findDeckCombos(cards, colorIdentity).then((data) => {
      if (myRequestId !== requestId || !document.body.contains(container)) return;
      if (!data) {
        setDynamicCombos([], 'error');
        container.querySelector('#toc-combos').innerHTML = comboAnalysisSectionHtml(initialStats, 'error');
        container.querySelector('#bracket-analysis-content').innerHTML =
          bracketAnalysisSectionHtml(initialStats, 'error');
        container.querySelector('#advice-content').innerHTML =
          adviceSectionHtml(initialStats, 'error');
        restoreManaAdviceControls();
        wireComboAnalysisRetry(savedDeck, parsed, resolved, myRequestId, initialStats, setDynamicCombos);
        return;
      }
      const stats = analyzeDeck(parsed.commanders, parsed.mainDeck, resolved, data);
      stats.manaAdvice = initialStats.manaAdvice;
      setDynamicCombos(stats.bracketAnalysis.combos, 'ready');
      container.querySelector('#toc-combos').innerHTML = comboAnalysisSectionHtml(stats, 'loaded');
      container.querySelector('#bracket-analysis-content').innerHTML =
        bracketAnalysisSectionHtml(stats, 'loaded');
      container.querySelector('#advice-content').innerHTML =
        adviceSectionHtml(stats, 'loaded', data);
      restoreManaAdviceControls();
    });
  }

  function wireComboAnalysisRetry(savedDeck, parsed, resolved, myRequestId, initialStats, setDynamicCombos) {
    const retry = () =>
      loadComboAnalysis(savedDeck, parsed, resolved, myRequestId, initialStats, setDynamicCombos);
    container.querySelectorAll('[data-combo-analysis-retry]').forEach((button) => {
      button.addEventListener('click', retry);
    });
  }

  function loadArchetypeSuggestions(root, deckSource, myRequestId) {
    root.innerHTML = `<p class="empty-state"><span class="spinner" aria-hidden="true"></span>${t('an.picker.loading')}</p>`;
    analyzeArchetypes(deckSource).then((res) => {
      if (myRequestId !== requestId || !document.body.contains(root)) return;
      if (!res.ok || !res.data) {
        root.innerHTML = `<p class="issue-list">🛑 ${escapeHtml(t('an.playstyleLoadFailed'))}</p>`;
        return;
      }
      root.innerHTML = archetypeSuggestionsHtml(res.data);
    });
  }

  return { loadDeck, onShown };

  function emptyShellHtml() {
    return `
      <div class="analyze-panel">
        <h2>${t('an.title')}</h2>
        ${deckPickerHtml()}
        <p class="empty-state">${t('an.pickHint')}</p>
      </div>
    `;
  }

  function loadingShellHtml(deckName) {
    return `
      <div class="analyze-panel">
        <h2>${t('an.title')}</h2>
        ${deckPickerHtml()}
        <p class="analyze-deck-name">${escapeHtml(deckName?.trim() || t('common.unnamedDeck'))}</p>
        <p class="empty-state"><span class="spinner" aria-hidden="true"></span>${t('an.loadingCards')}</p>
      </div>
    `;
  }
}

// --- Sub-tabs (Statische/Dynamische/Bracket-Analyse) -----------------------

const ANALYZE_SUBTABS = [
  { key: 'static', label: t('an.subtab.static') },
  { key: 'dynamic', label: t('an.subtab.dynamic') },
  { key: 'bracket', label: t('an.subtab.bracket') },
  { key: 'advice', label: t('an.subtab.advice') },
];

function analyzeSubtabsHtml() {
  const buttons = ANALYZE_SUBTABS.map(
    (tab, i) =>
      `<button type="button" class="analyze-subtab${i === 0 ? ' active' : ''}" data-subtab="${tab.key}">${escapeHtml(tab.label)}</button>`
  ).join('');
  return `<div class="analyze-subtabs" role="tablist">${buttons}</div>`;
}

/** Wires the sub-tab buttons rendered by `analyzeSubtabsHtml` to show/hide their `.analyze-subtab-panel`. */
function wireAnalyzeTabs(container) {
  const buttons = container.querySelectorAll('.analyze-subtab');
  const panels = container.querySelectorAll('.analyze-subtab-panel');
  buttons.forEach((btn) => {
    btn.addEventListener('click', () => {
      buttons.forEach((b) => b.classList.toggle('active', b === btn));
      panels.forEach((p) => p.classList.toggle('active', p.dataset.subtabPanel === btn.dataset.subtab));
    });
  });
}

function wireAdviceCurveView(container) {
  container.addEventListener('click', (event) => {
    const button = event.target.closest('[data-advice-curve-view]');
    if (!button) return;
    const card = button.closest('[data-advice-curve-card]');
    if (!card) return;
    const view = button.dataset.adviceCurveView;
    card.querySelectorAll('[data-advice-curve-view]').forEach((toggle) => {
      toggle.setAttribute('aria-pressed', String(toggle === button));
    });
    card.querySelectorAll('[data-advice-curve-panel]').forEach((panel) => {
      panel.hidden = panel.dataset.adviceCurvePanel !== view;
    });
  });
}

const TOC_ENTRIES = [
  { id: 'toc-mana-curve', label: t('an.toc.manaCurve') },
  { id: 'toc-expected-mana-curve', label: t('an.toc.expectedMana') },
  { id: 'toc-type-distribution', label: t('an.toc.typeDistribution') },
  { id: 'toc-land-archetypes', label: t('an.toc.landArchetypes') },
  { id: 'toc-color-pips', label: t('an.toc.colorPips') },
  { id: 'toc-opening-hand', label: t('an.toc.openingHand') },
  { id: 'toc-accelerants', label: t('an.toc.accelerants') },
  { id: 'toc-command-zone', label: t('an.toc.commandZone') },
  { id: 'toc-combos', label: t('an.toc.combos') },
  { id: 'toc-playstyle', label: t('an.toc.playstyle') },
];

function tableOfContentsHtml() {
  const items = TOC_ENTRIES.map((e) => `<li><a href="#${e.id}">${escapeHtml(e.label)}</a></li>`).join('');
  return `
    <nav class="analyze-toc" aria-label="${escapeAttr(t('an.toc.title'))}">
      <strong class="analyze-toc-title">${t('an.toc.title')}</strong>
      <ul class="analyze-toc-list">${items}</ul>
    </nav>
  `;
}

function resultShellHtml(deckName, stats, pickerHtml, comboState) {
  return `
    <div class="analyze-panel">
      <h2>${t('an.title')}</h2>
      ${pickerHtml}
      <p class="analyze-deck-name">${escapeHtml(deckName?.trim() || t('common.unnamedDeck'))}</p>
      ${commanderLineHtml(stats.commanders)}
      ${unresolvedWarningHtml(stats.unresolvedNames)}
      ${analyzeSubtabsHtml()}

      <div class="analyze-subtab-panel active" data-subtab-panel="static">
        ${tableOfContentsHtml()}
        <section class="analyze-section">
          <h3>${t('an.static.heading')}</h3>
          <p class="hint">${escapeHtml(t('an.static.hint'))}</p>

          ${summaryTilesHtml(stats)}
          <div id="toc-mana-curve">${manaCurveSectionHtml(stats)}</div>
          <div id="toc-expected-mana-curve">${expectedManaCurveSectionHtml(stats)}</div>
          <div id="toc-type-distribution">${typeDistributionSectionHtml(stats)}</div>
          <div id="toc-land-archetypes">${landArchetypesSectionHtml(stats)}</div>
          <div id="toc-color-pips">${colorPipsSectionHtml(stats)}</div>
          <div id="toc-opening-hand">${openingHandSectionHtml(stats)}</div>
          <div id="toc-accelerants">${accelerantsSectionHtml(stats)}</div>
          <div id="toc-command-zone">${commandZoneSectionHtml(stats)}</div>
          <div id="toc-combos">${comboAnalysisSectionHtml(stats, comboState)}</div>
          <div id="toc-playstyle"><div id="toc-playstyle-content"></div></div>
        </section>
      </div>

      <div class="analyze-subtab-panel" data-subtab-panel="dynamic">
        <div id="analyze-simulation-root"></div>
      </div>

      <div class="analyze-subtab-panel" data-subtab-panel="bracket">
        <div id="bracket-analysis-content">${bracketAnalysisSectionHtml(stats, comboState)}</div>
      </div>

      <div class="analyze-subtab-panel" data-subtab-panel="advice">
        <div id="advice-content">${adviceSectionHtml(stats, comboState)}</div>
      </div>
    </div>
  `;
}

function commanderLineHtml(commanders) {
  if (!commanders.length) return '';
  const items = commanders
    .map((c) => {
      const pips = colorPipBadgesHtml(c.colorIdentity);
      return `<span class="analyze-commander-entry">👑 ${cardNameHtml(c.name)} (${t('an.col.mv')} ${c.cmc})${pips}</span>`;
    })
    .join(' ');
  return `<p class="analyze-commander-line">${items}</p>`;
}

function unresolvedWarningHtml(names) {
  if (!names.length) return '';
  return `
    <ul class="issue-list not-found-list">
      <li>🛑 ${escapeHtml(t('an.unresolved', { count: names.length, names: names.join(', ') }))}</li>
    </ul>
  `;
}

function colorPipBadgesHtml(colors) {
  if (!colors || !colors.length) {
    return ` <span class="color-identity"><span class="color-pip color-pip--c" title="${escapeAttr(t('common.color.C'))}">C</span></span>`;
  }
  const pips = ['W', 'U', 'B', 'R', 'G']
    .filter((c) => colors.includes(c))
    .map((c) => `<span class="color-pip color-pip--${COLOR_CLASS[c]}" title="${escapeAttr(COLOR_NAMES[c])}">${c}</span>`)
    .join('');
  return ` <span class="color-identity">${pips}</span>`;
}

function fmt(n, digits = 1) {
  return fmtNumber(n, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function statTileHtml(label, value, hint = '') {
  return `
    <div class="analyze-stat-tile">
      <span class="analyze-stat-value">${value}</span>
      <span class="analyze-stat-label">${escapeHtml(label)}</span>
      ${hint ? `<span class="analyze-stat-hint">${escapeHtml(hint)}</span>` : ''}
    </div>
  `;
}

function summaryTilesHtml(stats) {
  const { manaValue, librarySize } = stats;
  return `
    <div class="analyze-stat-grid">
      ${statTileHtml(t('an.tile.tutors'), stats.tutorCount, t('an.tile.tutorsHint'))}
      ${statTileHtml(t('an.tile.lands'), manaValue.landCount, librarySize ? `${fmt((manaValue.landCount / librarySize) * 100, 0)}%` : '')}
      ${statTileHtml(t('an.tile.avgMvWithLands'), fmt(manaValue.averageWithLands))}
      ${statTileHtml(t('an.tile.avgMvWithoutLands'), fmt(manaValue.averageWithoutLands))}
      ${statTileHtml(t('an.tile.totalMv'), manaValue.total)}
      ${statTileHtml(t('an.tile.accelerants'), stats.openingHand.accelerantCount, t('an.tile.accelerantsHint'))}
    </div>
  `;
}

// --- Mana curve (bar chart + always-visible table) ------------------------

function manaCurveSectionHtml(stats) {
  const buckets = stats.manaCurve;
  const max = Math.max(...buckets.map((b) => b.count), 1);
  const BAR_MAX_PX = 130;

  const bars = buckets
    .map((b) => {
      const px = Math.round((b.count / max) * BAR_MAX_PX);
      const names = b.names
        .slice()
        .sort((a, c) => a.name.localeCompare(c.name))
        .map((n) => (n.qty > 1 ? `${n.name} ×${n.qty}` : n.name))
        .join(', ');
      const title = names || t('an.noCards');
      return `
        <div class="bar-col">
          <span class="bar-value">${b.count || ''}</span>
          <div class="bar-col-track">
            <div class="bar-col-fill" style="height:${px}px" title="${escapeAttr(title)}"></div>
          </div>
          <span class="bar-col-label">${b.cmc}</span>
        </div>
      `;
    })
    .join('');

  const rows = buckets
    .filter((b) => b.count > 0)
    .map((b) => {
      const names = b.names
        .slice()
        .sort((a, c) => a.name.localeCompare(c.name))
        .map((n) => cardNameHtml(n.name, n.qty))
        .join(', ');
      return `<tr><td>${b.cmc}</td><td>${b.count}</td><td>${names}</td></tr>`;
    })
    .join('');

  return `
    <div class="analyze-chart-card">
      <h4>${t('an.manaCurve.heading')}</h4>
      <p class="hint">${t('an.manaCurve.hint')}</p>
      <div class="bar-chart bar-chart--columns">${bars}</div>
      <table class="analyze-table">
        <thead><tr><th>${t('an.col.mv')}</th><th>${t('an.col.count')}</th><th>${t('an.col.cards')}</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
  `;
}

// --- Expected mana curve (line chart + table) ------------------------------

function expectedManaCurveSectionHtml(stats) {
  const points = stats.expectedManaCurve;
  const svg = expectedCurveSvg(points);
  const last = points[points.length - 1];

  const rows = points
    .map(
      (p) =>
        `<tr><td>${p.turn}</td><td>${fmt(p.withoutRamp)}</td><td>${fmt(p.withRampRealistic)}</td><td>${fmt(p.withRampMax)}</td></tr>`
    )
    .join('');

  return `
    <div class="analyze-chart-card">
      <h4>${t('an.expectedMana.heading')}</h4>
      <p class="hint">${escapeHtml(t('an.expectedMana.hint'))}</p>
      <div class="line-legend">
        <span class="line-legend-item"><span class="line-key line-key--context"></span>${escapeHtml(t('an.expectedMana.legendLands', { turn: last.turn, value: fmt(last.withoutRamp) }))}</span>
        <span class="line-legend-item"><span class="line-key line-key--info"></span>${escapeHtml(t('an.expectedMana.legendRealistic', { turn: last.turn, value: fmt(last.withRampRealistic) }))}</span>
        <span class="line-legend-item"><span class="line-key line-key--accent"></span>${escapeHtml(t('an.expectedMana.legendMax', { turn: last.turn, value: fmt(last.withRampMax) }))}</span>
      </div>
      ${svg}
      <table class="analyze-table">
        <thead><tr><th>${t('an.col.turn')}</th><th>${t('an.expectedMana.colLands')}</th><th>${t('an.expectedMana.colRealistic')}</th><th>${t('an.expectedMana.colMax')}</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
  `;
}

function expectedCurveSvg(points) {
  const width = 560;
  const height = 200;
  const padding = { top: 16, right: 16, bottom: 26, left: 28 };
  const plotW = width - padding.left - padding.right;
  const plotH = height - padding.top - padding.bottom;
  const maxY = Math.max(...points.map((p) => p.withRampMax), 1);
  const n = points.length;
  const xFor = (i) => padding.left + (n > 1 ? (i / (n - 1)) * plotW : 0);
  const yFor = (v) => padding.top + plotH - (v / maxY) * plotH;

  const gridSteps = 4;
  const gridLines = Array.from({ length: gridSteps + 1 }, (_, i) => {
    const value = Math.round((maxY * i) / gridSteps);
    const y = yFor(value);
    return `
      <line x1="${padding.left}" y1="${y}" x2="${width - padding.right}" y2="${y}" class="chart-gridline" />
      <text x="${padding.left - 6}" y="${y + 3}" class="chart-axis-text" text-anchor="end">${value}</text>
    `;
  }).join('');

  const xLabels = points
    .map((p, i) => `<text x="${xFor(i)}" y="${height - 8}" class="chart-axis-text" text-anchor="middle">${p.turn === points[points.length - 1].turn ? p.turn + '+' : p.turn}</text>`)
    .join('');

  const polyline = (key, cls) =>
    `<polyline points="${points.map((p, i) => `${xFor(i)},${yFor(p[key])}`).join(' ')}" class="${cls}" fill="none" />`;
  const dots = (key, cls) =>
    points.map((p, i) => `<circle cx="${xFor(i)}" cy="${yFor(p[key])}" r="4" class="${cls}" />`).join('');

  return `
    <svg viewBox="0 0 ${width} ${height}" class="analyze-svg" role="img" aria-label="${escapeAttr(t('an.expectedMana.svgAria'))}">
      ${gridLines}
      ${polyline('withoutRamp', 'chart-line chart-line--context')}
      ${polyline('withRampRealistic', 'chart-line chart-line--info')}
      ${polyline('withRampMax', 'chart-line chart-line--accent')}
      ${dots('withoutRamp', 'chart-dot chart-dot--context')}
      ${dots('withRampRealistic', 'chart-dot chart-dot--info')}
      ${dots('withRampMax', 'chart-dot chart-dot--accent')}
      ${xLabels}
    </svg>
  `;
}

// --- Type distribution (horizontal bars) -----------------------------------

function typeDistributionSectionHtml(stats) {
  const rows = stats.typeDistribution.filter((t) => t.count > 0);
  const max = Math.max(...rows.map((t) => t.count), 1);
  if (!rows.length) return '';

  const bars = rows
    .map(
      (t) => `
        <div class="bar-row">
          <span class="bar-row-label">${escapeHtml(t.label)}</span>
          <div class="bar-row-track">
            <div class="bar-row-fill" style="width:${(t.count / max) * 100}%"></div>
          </div>
          <span class="bar-row-value">${t.count}</span>
        </div>
      `
    )
    .join('');

  return `
    <div class="analyze-chart-card">
      <h4>${t('an.typeDist.heading')}</h4>
      <p class="hint">${t('an.typeDist.hint')}</p>
      <div class="bar-chart bar-chart--rows">${bars}</div>
    </div>
  `;
}

// --- Land archetypes (horizontal bars + table) ------------------------------

function landArchetypesSectionHtml(stats) {
  const rows = stats.landArchetypes;
  if (!rows.length) return '';
  const max = Math.max(...rows.map((a) => a.count), 1);

  const bars = rows
    .map(
      (a) => `
        <div class="bar-row">
          <span class="bar-row-label">${escapeHtml(a.label)}</span>
          <div class="bar-row-track">
            <div class="bar-row-fill" style="width:${(a.count / max) * 100}%"></div>
          </div>
          <span class="bar-row-value">${a.count}</span>
        </div>
      `
    )
    .join('');

  const tableRows = rows
    .map((a) => {
      const names = a.names
        .slice()
        .sort((x, y) => x.name.localeCompare(y.name))
        .map((n) => cardNameHtml(n.name, n.qty))
        .join(', ');
      return `<tr><td>${escapeHtml(a.label)}</td><td>${a.count}</td><td>${names}</td></tr>`;
    })
    .join('');

  return `
    <div class="analyze-chart-card">
      <h4>${t('an.landArch.heading')}</h4>
      <p class="hint">${escapeHtml(t('an.landArch.hint'))}</p>
      <div class="bar-chart bar-chart--rows">${bars}</div>
      <table class="analyze-table">
        <thead><tr><th>${t('an.landArch.colArchetype')}</th><th>${t('an.col.count')}</th><th>${t('an.landArch.colLands')}</th></tr></thead>
        <tbody>${tableRows}</tbody>
      </table>
    </div>
  `;
}

// --- Color pips: card requirements vs. mana sources ------------------------

function colorPipsSectionHtml(stats) {
  const { cards, sources } = stats.colorPips;
  const max = Math.max(...Object.values(cards), ...Object.values(sources), 1);

  const rows = ['W', 'U', 'B', 'R', 'G']
    .map((color) => {
      const cls = COLOR_CLASS[color];
      return `
        <div class="pip-compare-row">
          <span class="pip-compare-label"><span class="color-pip color-pip--${cls}" title="${COLOR_NAMES[color]}">${color}</span></span>
          <div class="pip-compare-bars">
            <div class="bar-row-track pip-compare-track">
              <div class="bar-row-fill pip-fill--${cls} pip-fill--cards" style="width:${(cards[color] / max) * 100}%"></div>
            </div>
            <span class="pip-compare-value">${cards[color]}</span>
            <div class="bar-row-track pip-compare-track">
              <div class="bar-row-fill pip-fill--${cls} pip-fill--sources" style="width:${(sources[color] / max) * 100}%"></div>
            </div>
            <span class="pip-compare-value">${sources[color]}</span>
          </div>
        </div>
      `;
    })
    .join('');

  return `
    <div class="analyze-chart-card">
      <h4>${t('an.colorPips.heading')}</h4>
      <p class="hint">${escapeHtml(t('an.colorPips.hint'))}</p>
      <div class="pip-compare-legend">
        <span class="line-legend-item"><span class="line-key line-key--solid"></span>${t('an.colorPips.legendDemand')}</span>
        <span class="line-legend-item"><span class="line-key line-key--light"></span>${t('an.colorPips.legendSources')}</span>
      </div>
      <div class="pip-compare-chart">${rows}</div>
    </div>
  `;
}

// --- Opening hand (hypergeometric) -----------------------------------------

function openingHandSectionHtml(stats) {
  const {
    landCount,
    fetchCount,
    accelerantCount,
    expectedLands,
    expectedLandsPlusAccel,
    landProbabilities,
    landsOverTime,
    librarySize,
  } = stats.openingHand;

  const probRow = landProbabilities
    .map((lp) => `<div class="prob-col"><span class="prob-col-value">${(lp.p * 100).toFixed(0)}%</span><span class="prob-col-label">${lp.k}</span></div>`)
    .join('');

  const lastTurn = landsOverTime[landsOverTime.length - 1];
  const fetchBonusAtEnd = lastTurn.withFetchBonus - lastTurn.withoutFetchBonus;

  const overTimeRows = landsOverTime
    .map(
      (row) =>
        `<tr><td>${row.turn === 1 ? t('an.openingHand.turn1') : row.turn}</td><td>${fmt(row.withoutFetchBonus)}</td><td>${fmt(row.withFetchBonus)}</td></tr>`
    )
    .join('');

  const fetchHint = fetchCount
    ? `<p class="hint">${escapeHtml(t('an.openingHand.fetchHint', { count: fetchCount, turn: lastTurn.turn, bonus: fmt(fetchBonusAtEnd, 2) }))}</p>`
    : '';

  return `
    <div class="analyze-chart-card">
      <h4>${escapeHtml(t('an.openingHand.heading', { size: librarySize }))}</h4>
      <div class="analyze-stat-grid analyze-stat-grid--compact">
        ${statTileHtml(t('an.openingHand.tileAvgLands'), fmt(expectedLands))}
        ${statTileHtml(t('an.openingHand.tileAvgLandsAccel'), fmt(expectedLandsPlusAccel))}
        ${statTileHtml(t('an.openingHand.tileLandsInDeck'), landCount)}
        ${statTileHtml(t('an.openingHand.tileFetchlands'), fetchCount)}
        ${statTileHtml(t('an.openingHand.tileAccelInDeck'), accelerantCount)}
      </div>
      <p class="hint">${t('an.openingHand.probHint')}</p>
      <div class="prob-row">${probRow}</div>

      <p class="hint" style="margin-top:0.8rem">${t('an.openingHand.overTimeHint')}</p>
      ${fetchHint}
      <table class="analyze-table">
        <thead><tr><th>${t('an.col.turn')}</th><th>${t('an.openingHand.colWithoutFetch')}</th><th>${t('an.openingHand.colWithFetch')}</th></tr></thead>
        <tbody>${overTimeRows}</tbody>
      </table>
    </div>
  `;
}

// --- Accelerant lists (transparency for the classification heuristic) ------

function accelerantsSectionHtml(stats) {
  const { manaRocks, manaDorks, manaLandAuras, landRampSpells, rituals, treasureGenerators } = stats.accelerants;
  const groups = [manaRocks, manaDorks, manaLandAuras, landRampSpells, rituals, treasureGenerators];
  if (groups.every((g) => !g.length)) {
    return `
      <div class="analyze-chart-card">
        <h4>${t('an.accel.heading')}</h4>
        <p class="empty-state">${t('an.accel.none')}</p>
      </div>
    `;
  }
  const list = (title, items) => {
    if (!items.length) return '';
    const li = items
      .slice()
      .sort((a, b) => a.name.localeCompare(b.name))
      .map((c) => `<li>${cardNameHtml(c.name, c.qty)} <span class="accelerant-cmc">${t('an.col.mv')} ${c.cmc}</span></li>`)
      .join('');
    return `<div class="accelerant-group"><strong>${title} (${items.length})</strong><ul class="card-list">${li}</ul></div>`;
  };
  return `
    <div class="analyze-chart-card">
      <h4>${t('an.accel.heading')}</h4>
      <p class="hint">${escapeHtml(t('an.accel.hint'))}</p>
      <div class="accelerant-groups">
        ${list(t('an.accel.manaRocks'), manaRocks)}
        ${list(t('an.accel.manaDorks'), manaDorks)}
        ${list(t('an.accel.landAuras'), manaLandAuras)}
        ${list(t('an.accel.landRamp'), landRampSpells)}
        ${list(t('an.accel.rituals'), rituals)}
        ${list(t('an.accel.treasure'), treasureGenerators)}
      </div>
    </div>
  `;
}

// --- Command Zone deckbuilding-template categories --------------------------

function commandZoneSectionHtml(stats) {
  const { categories, targetedDisruption, massDisruption, cardAdvantage, tutors } = stats.commandZone;
  const max = Math.max(...categories.map((c) => c.count), 1);

  const bars = categories
    .map(
      (c) => `
        <div class="bar-row">
          <span class="bar-row-label">${escapeHtml(c.label)}</span>
          <div class="bar-row-track">
            <div class="bar-row-fill" style="width:${(c.count / max) * 100}%"></div>
          </div>
          <span class="bar-row-value">${c.count}</span>
        </div>
      `
    )
    .join('');

  const nameList = (names) =>
    names
      .slice()
      .sort((x, y) => x.name.localeCompare(y.name))
      .map((n) => cardNameHtml(n.name, n.qty))
      .join(', ');

  const tableRows = categories
    .map((c) => `<tr><td>${escapeHtml(c.label)}</td><td>${c.count}</td><td>${nameList(c.names)}</td></tr>`)
    .join('');

  const subKindTable = (title, rows) => {
    if (!rows.length) return '';
    const trs = rows
      .map((r) => `<tr><td>${escapeHtml(r.label)}</td><td>${r.count}</td><td>${nameList(r.names)}</td></tr>`)
      .join('');
    return `
      <h5>${escapeHtml(title)}</h5>
      <table class="analyze-table">
        <thead><tr><th>${t('an.commandZone.colType')}</th><th>${t('an.col.count')}</th><th>${t('an.col.cards')}</th></tr></thead>
        <tbody>${trs}</tbody>
      </table>
    `;
  };

  const tutorListHtml = (items) => {
    if (!items.length) return '';
    const total = items.reduce((s, c) => s + c.qty, 0);
    const li = items
      .slice()
      .sort((a, b) => a.name.localeCompare(b.name))
      .map((c) => `<li>${cardNameHtml(c.name, c.qty)}</li>`)
      .join('');
    return `
      <h5>${escapeHtml(t('an.commandZone.tutorsHeading', { count: total }))}</h5>
      <p class="hint">${t('an.commandZone.tutorsHint')}</p>
      <ul class="card-list">${li}</ul>
    `;
  };

  return `
    <div class="analyze-chart-card">
      <h4>${t('an.commandZone.heading')}</h4>
      <p class="hint">${escapeHtml(t('an.commandZone.hint'))}</p>
      <div class="bar-chart bar-chart--rows">${bars}</div>
      <table class="analyze-table">
        <thead><tr><th>${t('an.commandZone.colCategory')}</th><th>${t('an.col.count')}</th><th>${t('an.col.cards')}</th></tr></thead>
        <tbody>${tableRows}</tbody>
      </table>
      ${subKindTable(t('an.commandZone.cardAdvantageDetails'), cardAdvantage)}
      ${subKindTable(t('an.commandZone.targetedDetails'), targetedDisruption)}
      ${subKindTable(t('an.commandZone.massDetails'), massDisruption)}
      ${tutorListHtml(tutors)}
    </div>
  `;
}

// --- Playstyle / archetype-likelihood suggestions (backend-scored) --------
// Named "Spielstil-Analyse" rather than "Archetyp-Analyse" to avoid reading
// as the same thing as "Land-Archetypen" above (an unrelated land/ramp
// categorization) — see docs/implementation-state/BACKLOG.md.

function archetypeSuggestionsHtml({ suggestions = [], typalSignals = [] }) {
  const bars = suggestions
    .map(
      (s) => `
        <div class="bar-row">
          <span class="bar-row-label" title="${escapeAttr(s.description || '')}">${escapeHtml(s.label)}</span>
          <div class="bar-row-track">
            <div class="bar-row-fill" style="width:${s.percent}%"></div>
          </div>
          <span class="bar-row-value">${s.percent}%</span>
        </div>
      `
    )
    .join('');

  const typalItems = typalSignals
    .map(
      (sig) =>
        `<li>${escapeHtml(t('an.playstyle.typalItem', { type: sig.creatureType, count: sig.count, share: Math.round(sig.share * 100) }))}</li>`
    )
    .join('');

  return `
    <div class="analyze-chart-card">
      <h4>${t('an.playstyle.heading')}</h4>
      <p class="hint">${escapeHtml(t('an.playstyle.hint'))}</p>
      ${bars ? `<div class="bar-chart bar-chart--rows">${bars}</div>` : `<p class="empty-state">${t('an.playstyle.noSignals')}</p>`}
      ${typalItems ? `<h5>${t('an.playstyle.typalHeading')}</h5><ul class="card-list">${typalItems}</ul>` : ''}
    </div>
  `;
}

function comboAnalysisSectionHtml(stats, state) {
  if (state === 'loading') {
    return `
      <section class="analyze-section">
        <h3>${t('an.combos.heading')}</h3>
        <p class="hint">${escapeHtml(t('an.combos.hint'))}</p>
        <p class="empty-state"><span class="spinner" aria-hidden="true"></span>${t('an.combos.loading')}</p>
      </section>`;
  }
  if (state === 'incomplete') {
    return `
      <section class="analyze-section">
        <h3>${t('an.combos.heading')}</h3>
        <p class="hint">${escapeHtml(t('an.combos.hint'))}</p>
        <p class="server-status warning">${t('an.combos.incomplete')}</p>
      </section>`;
  }
  if (state === 'error') {
    return `
      <section class="analyze-section">
        <h3>${t('an.combos.heading')}</h3>
        <p class="hint">${escapeHtml(t('an.combos.hint'))}</p>
        <p class="server-status warning">${t('an.combos.unavailable')}</p>
        <button type="button" id="combo-analysis-retry" data-combo-analysis-retry>${t('an.combos.retry')}</button>
      </section>`;
  }

  const combos = stats.bracketAnalysis.combos;
  if (!combos.length) {
    return `
      <section class="analyze-section">
        <h3>${t('an.combos.heading')}</h3>
        <p class="hint">${escapeHtml(t('an.combos.hint'))}</p>
        <p class="empty-state">${t('an.combos.none')}</p>
      </section>`;
  }

  const rows = combos.map((combo) => {
    const cards = combo.uses
      .map((use) => `${cardNameHtml(use.name, use.quantity)}`)
      .join(' + ');
    const results = combo.produces?.length
      ? `<p>${escapeHtml(t('an.combos.produces', { results: combo.produces.join(', ') }))}</p>`
      : '';
    const manaValue = combo.totalManaValue === null
      ? t('an.combos.unknownManaValue')
      : t('an.combos.manaValue', { value: fmtNumber(combo.totalManaValue) });
    const turn = combo.earliestTurn === null
      ? t('an.combos.afterCurve')
      : t('an.combos.earliestTurn', { turn: combo.earliestTurn });
    const requirements = combo.hasUnverifiedRequirements
      ? `<p class="hint">${escapeHtml(t('an.combos.requirements', { requirements: combo.requirements.join(', ') }))}</p>`
      : '';
    return `<li>
      <strong>${cards}</strong>
      <span class="hint"> — ${escapeHtml(t('an.combos.cardCount', { count: combo.cardCount }))}; ${escapeHtml(manaValue)}; ${escapeHtml(turn)}</span>
      ${results}${requirements}
    </li>`;
  }).join('');

  return `
    <section class="analyze-section">
      <h3>${t('an.combos.heading')} (${combos.length})</h3>
      <p class="hint">${escapeHtml(t('an.combos.hint'))}</p>
      <ul class="card-list">${rows}</ul>
    </section>`;
}

// --- Bracket analysis (WotC "Commander Brackets" heuristic approximation) --

function bracketAnalysisSectionHtml(stats, comboState) {
  const {
    gameChangers,
    massLandDenial,
    extraTurnSpells,
    combos,
    comboUnknownCount,
    minimumBracket,
    reasons,
  } = stats.bracketAnalysis;

  const list = (title, items) => {
    const total = items.reduce((s, c) => s + c.qty, 0);
    if (!items.length) {
      return `<div class="accelerant-group"><strong>${escapeHtml(title)} (0)</strong><p class="empty-state">${t('an.bracket.noneDetected')}</p></div>`;
    }
    const li = items
      .slice()
      .sort((a, b) => a.name.localeCompare(b.name))
      .map((c) => `<li>${cardNameHtml(c.name, c.qty)}</li>`)
      .join('');
    return `<div class="accelerant-group"><strong>${escapeHtml(title)} (${total})</strong><ul class="card-list">${li}</ul></div>`;
  };

  const verdictText = minimumBracket
    ? t('an.bracket.verdict', { bracket: minimumBracket })
    : t('an.bracket.verdictNone');

  const reasonsHtml = reasons.length
    ? `<ul class="issue-list">${reasons.map((r) => `<li>${escapeHtml(r)}</li>`).join('')}</ul>`
    : '';
  const comboSignals = combos.filter(
    (combo) => combo.bracketImpact === 'bracket3' || combo.bracketImpact === 'bracket4'
  );
  const comboSignalRows = comboSignals.map((combo) => {
    const cards = combo.uses
      .map((use) => cardNameHtml(use.name, use.quantity))
      .join(' + ');
    const impact = combo.bracketImpact === 'bracket4'
      ? t('an.bracket.comboImpact4')
      : t('an.bracket.comboImpact3');
    const turn = combo.earliestTurn === null
      ? t('an.bracket.comboSignalManaUnknown')
      : t('an.bracket.comboSignalTurn', { turn: combo.earliestTurn });
    const output = combo.produces?.length
      ? `<span class="hint">${escapeHtml(t('an.bracket.comboSignalOutput', { results: combo.produces.join(', ') }))}</span>`
      : '';
    return `<li><strong>${cards}</strong> — ${escapeHtml(impact)}; ${escapeHtml(turn)}${output ? `<br>${output}` : ''}</li>`;
  }).join('');
  const comboSignalGroup = comboState === 'loaded'
    ? `<div class="accelerant-group">
        <strong>${escapeHtml(t('an.bracket.combos'))}</strong>
        <p class="hint">${escapeHtml(t('an.bracket.comboSignalCount', { found: combos.length, signals: comboSignals.length }))}</p>
        ${
          comboSignalRows
            ? `<ul class="card-list">${comboSignalRows}</ul>`
            : `<p class="empty-state">${t('an.bracket.noneDetected')}</p>`
        }
        ${
          comboUnknownCount
            ? `<p class="hint">${escapeHtml(t('an.bracket.comboNotCounted', { count: comboUnknownCount }))}</p>`
            : ''
        }
      </div>`
    : '';
  const comboSummary =
    comboState === 'loading'
      ? `<p class="hint"><span class="spinner" aria-hidden="true"></span>${t('an.bracket.combosLoading')}</p>`
      : comboState === 'error'
        ? `<p class="server-status warning">${t('an.bracket.combosUnavailable')}</p>`
        : comboState === 'incomplete'
          ? `<p class="server-status warning">${t('an.bracket.combosIncomplete')}</p>`
          : `<p class="hint">${escapeHtml(
              t('an.bracket.comboSummary', {
                total: stats.bracketAnalysis.combos.length,
                twoCard: stats.bracketAnalysis.comboTwoCardCount,
                early: stats.bracketAnalysis.comboEarlyTwoCardCount,
              })
            )}</p>`;

  return `
    <section class="analyze-section">
      <h3>${t('an.bracket.heading')}</h3>
      <p class="hint">${escapeHtml(t('an.bracket.hint'))}</p>
      <div class="analyze-chart-card">
        <h4>${escapeHtml(verdictText)}</h4>
        ${reasonsHtml}
        ${comboSummary}
      </div>
      <div class="analyze-chart-card">
        <h4>${t('an.bracket.signalsHeading')}</h4>
        <div class="accelerant-groups">
          ${list(t('an.bracket.gameChangers'), gameChangers)}
          ${list(t('an.bracket.massLandDenial'), massLandDenial)}
          ${list(t('an.bracket.extraTurns'), extraTurnSpells)}
          ${comboSignalGroup}
        </div>
      </div>
    </section>
  `;
}

// --- Advice (Commander mana-curve guide + related Spellbook variants) -----

function adviceSectionHtml(stats, comboState, comboData = null) {
  return `
    <section class="analyze-section">
      ${adviceHeaderHtml()}
      ${adviceSummaryBarHtml(stats, comboState, comboData)}
      ${adviceCurveHtml(stats)}
      ${adviceManaBaseHtml(stats)}
      <div class="analyze-chart-card" data-mana-advice>${manaAdviceHtml(stats.manaAdvice)}</div>
      ${relatedComboAdviceHtml(comboState, comboData, stats)}
    </section>
  `;
}

function adviceHeaderHtml() {
  return `
    <div class="advice-header-card">
      <div class="advice-header-content">
        <div class="advice-header-text">
          <h3>${t('an.advice.heading')}</h3>
          <p class="advice-header-subtitle">${escapeHtml(t('an.advice.guideSub'))}</p>
        </div>
        <a href="https://www.tcgplayer.com/content/article/What-s-an-Optimal-Mana-Curve-and-Land-Ramp-Count-for-Commander/e22caad1-b04b-4f8a-951b-a41e9f08da14/"
           class="advice-guide-button" target="_blank" rel="noopener noreferrer">
          <span>${escapeHtml(t('an.advice.guideLink'))}</span>
          <span class="advice-external-icon" aria-hidden="true">↗</span>
        </a>
      </div>
    </div>
  `;
}

function adviceSummaryBarHtml(stats, comboState, comboData) {
  const mdfcCount = stats.landArchetypes.find((item) => item.key === 'mdfc_land')?.count || 0;
  const effectiveLands = stats.manaValue.landCount + mdfcCount / 2;
  const manaRocks = stats.accelerants.manaRocks;
  const rockCount = manaRocks.reduce((sum, rock) => sum + rock.qty, 0);
  const includesSolRing = manaRocks.some((rock) => rock.name.trim().toLowerCase() === 'sol ring');

  let targetLands = GUIDE_BASE_LANDS;
  let targetRocks = GUIDE_BASE_MANA_ROCKS;
  let hasCommanderRef = false;

  for (const cmdr of stats.commanders) {
    const ref = COMMANDER_CURVE_REFERENCE[cmdr.cmc];
    if (ref) {
      targetLands = ref.lands;
      targetRocks = ref.rocks;
      hasCommanderRef = true;
      break;
    }
  }

  if (!hasCommanderRef && includesSolRing) {
    const additionalRocks = Math.max(0, rockCount - GUIDE_BASE_MANA_ROCKS);
    targetLands = Math.max(
      GUIDE_MIN_MIDRANGE_LANDS,
      GUIDE_BASE_LANDS - Math.floor(additionalRocks / GUIDE_ROCKS_PER_LAND_CUT.min)
    );
    targetRocks = rockCount;
  }

  const landDiff = targetLands - effectiveLands;
  let landPill;
  if (effectiveLands < GUIDE_MIN_MIDRANGE_LANDS) {
    landPill = `<span class="advice-status-pill advice-status-pill--warn">&lt; 37 Floor</span>`;
  } else if (landDiff > 0) {
    landPill = `<span class="advice-status-pill advice-status-pill--warn">−${Math.ceil(landDiff)}</span>`;
  } else {
    landPill = `<span class="advice-status-pill advice-status-pill--ok">✓ ${t('an.advice.statusTargetReached')}</span>`;
  }

  const rockDiff = targetRocks - rockCount;
  let rockPill;
  if (rockDiff > 0) {
    rockPill = `<span class="advice-status-pill advice-status-pill--warn">−${rockDiff}</span>`;
  } else {
    rockPill = `<span class="advice-status-pill advice-status-pill--ok">✓ ${t('an.advice.statusTargetReached')}</span>`;
  }

  const nonRockSpellCount = Math.max(0, stats.manaValue.nonlandCount - rockCount);
  const spellsAtTwoToFour = [2, 3, 4].reduce((sum, manaValue) => {
    const bucket = stats.manaCurve.find((item) => Number(item.cmc) === manaValue);
    const rocksAtValue = manaRocks
      .filter((rock) => rock.cmc === manaValue)
      .reduce((subtotal, rock) => subtotal + rock.qty, 0);
    return sum + Math.max(0, (bucket?.count || 0) - rocksAtValue);
  }, 0);
  const curveRatio = nonRockSpellCount ? Math.round((spellsAtTwoToFour / nonRockSpellCount) * 100) : 0;
  const curvePill = curveRatio >= 50
    ? `<span class="advice-status-pill advice-status-pill--ok">✓ ${t('an.advice.statusOptimal')}</span>`
    : `<span class="advice-status-pill advice-status-pill--warn">⚠ ${t('an.advice.statusReview')}</span>`;

  const totalPipDemand = Object.values(stats.colorPips.cards).reduce((sum, count) => sum + count, 0);
  const totalPotentialSources = Object.values(stats.colorPips.sources).reduce((sum, count) => sum + count, 0);
  const colorGaps = Object.keys(COLOR_NAMES).filter((color) => {
    const demandShare = totalPipDemand ? stats.colorPips.cards[color] / totalPipDemand : 0;
    const sourceShare = totalPotentialSources ? stats.colorPips.sources[color] / totalPotentialSources : 0;
    return demandShare > sourceShare && ((stats.colorPips.cards[color] || 0) > 0 || (stats.colorPips.sources[color] || 0) > 0);
  });
  const colorPill = colorGaps.length === 0
    ? `<span class="advice-status-pill advice-status-pill--ok">✓ ${t('an.advice.statusBalanced')}</span>`
    : `<span class="advice-status-pill advice-status-pill--warn">⚠ ${colorGaps.length} ${t('an.advice.statusDeficit')}</span>`;

  const currentCombosCount = stats?.bracketAnalysis?.combos?.length || 0;
  let comboValue = String(currentCombosCount);
  let comboPill = `<span class="advice-status-pill advice-status-pill--neutral">—</span>`;
  if (comboState === 'loading') {
    comboValue = `${currentCombosCount} <small style="font-size:0.8rem;color:var(--text-dim);font-weight:normal">/ <span class="spinner" aria-hidden="true"></span></small>`;
    comboPill = `<span class="advice-status-pill advice-status-pill--neutral">${t('an.advice.combosLoading')}</span>`;
  } else if (comboState === 'loaded') {
    const recCount = comboData?.recommendations?.length || 0;
    comboValue = `${currentCombosCount} <small style="font-size:0.8rem;color:var(--text-dim);font-weight:normal">/ +${recCount} mögl.</small>`;
    comboPill = `<span class="advice-status-pill advice-status-pill--${currentCombosCount > 0 ? 'ok' : 'info'}">${t('an.advice.combosCurrentVsPossible', { current: currentCombosCount, possible: recCount })}</span>`;
  } else {
    comboPill = `<span class="advice-status-pill advice-status-pill--neutral">${t('an.advice.combosCurrentInDeck', { count: currentCombosCount })}</span>`;
  }

  return `
    <div class="advice-summary-grid">
      <div class="advice-summary-tile">
        <span class="advice-summary-label">${t('an.advice.summaryLands')}</span>
        <span class="advice-summary-value">${fmt(effectiveLands)} <small style="font-size:0.8rem;color:var(--text-dim);font-weight:normal">/ ${targetLands}</small></span>
        ${landPill}
      </div>
      <div class="advice-summary-tile">
        <span class="advice-summary-label">${t('an.advice.summaryRocks')}</span>
        <span class="advice-summary-value">${rockCount} <small style="font-size:0.8rem;color:var(--text-dim);font-weight:normal">/ ${targetRocks}</small></span>
        ${rockPill}
      </div>
      <div class="advice-summary-tile">
        <span class="advice-summary-label">${t('an.advice.summaryCurveFocus')}</span>
        <span class="advice-summary-value">${curveRatio}%</span>
        ${curvePill}
      </div>
      <div class="advice-summary-tile">
        <span class="advice-summary-label">${t('an.advice.summaryColors')}</span>
        <span class="advice-summary-value" style="font-size:1.05rem;line-height:1.5">${colorGaps.length === 0 ? t('an.advice.statusBalanced') : `${colorGaps.length} ${t('an.advice.statusDeficit')}`}</span>
        ${colorPill}
      </div>
      <div class="advice-summary-tile">
        <span class="advice-summary-label">${t('an.advice.summaryCombos')}</span>
        <span class="advice-summary-value">${comboValue}</span>
        ${comboPill}
      </div>
    </div>
  `;
}

function adviceCurveHtml(stats) {
  const manaRocks = stats.accelerants.manaRocks;
  const nonRockSpellCount = Math.max(
    0,
    stats.manaValue.nonlandCount - manaRocks.reduce((sum, rock) => sum + rock.qty, 0)
  );
  const spellsAtTwoToFour = [2, 3, 4].reduce((sum, manaValue) => {
    const bucket = stats.manaCurve.find((item) => Number(item.cmc) === manaValue);
    const rocksAtValue = manaRocks
      .filter((rock) => rock.cmc === manaValue)
      .reduce((subtotal, rock) => subtotal + rock.qty, 0);
    return sum + Math.max(0, (bucket?.count || 0) - rocksAtValue);
  }, 0);
  const isBalanced = nonRockSpellCount && (spellsAtTwoToFour / nonRockSpellCount > 0.5);
  const curveGuidance = nonRockSpellCount
    ? isBalanced
      ? t('an.advice.curveBalanced', { count: spellsAtTwoToFour, total: nonRockSpellCount })
      : t('an.advice.curveShift', { count: spellsAtTwoToFour, total: nonRockSpellCount })
    : t('an.advice.curveNoSpells');

  const commanderGuides = stats.commanders.map((commander) => {
    const reference = COMMANDER_CURVE_REFERENCE[commander.cmc];
    if (!reference) {
      return `<p class="hint">${escapeHtml(t('an.advice.noCommanderModel', { commander: commander.name, cmc: commander.cmc }))}</p>`;
    }

    const rows = reference.curve
      .map((expected, index) => {
        const manaValue = index + 1;
        const bucket = stats.manaCurve.find((item) => Number(item.cmc) === manaValue);
        const rocksAtValue = manaRocks
          .filter((rock) => rock.cmc === manaValue)
          .reduce((sum, rock) => sum + rock.qty, 0);
        const current = Math.max(0, (bucket?.count || 0) - rocksAtValue);
        const diff = current - expected;
        const diffClass = diff > 0 ? 'plus' : diff < 0 ? 'minus' : 'zero';
        const diffText = diff > 0 ? `+${diff}` : String(diff);
        const maxPair = Math.max(1, current, expected);
        const currentPct = Math.round((current / maxPair) * 100);
        const expectedPct = Math.round((expected / maxPair) * 100);

        return `
          <tr>
            <td><strong>${manaValue}</strong></td>
            <td>${current}</td>
            <td>${expected}</td>
            <td><span class="advice-diff advice-diff--${diffClass}">${diffText}</span></td>
            <td>
              <div class="advice-mini-compare" title="Deck: ${current} | Modell: ${expected}">
                <span class="advice-mini-compare-bar advice-curve-bar--deck" style="width:${Math.max(2, Math.round(currentPct * 0.45))}px"></span>
                <span class="advice-mini-compare-bar advice-curve-bar--model" style="width:${Math.max(2, Math.round(expectedPct * 0.45))}px"></span>
              </div>
            </td>
          </tr>
        `;
      })
      .join('');

    const maxCount = Math.max(
      1,
      ...reference.curve.map((expected, index) => {
        const manaValue = index + 1;
        const bucket = stats.manaCurve.find((item) => Number(item.cmc) === manaValue);
        const rocksAtValue = manaRocks
          .filter((rock) => rock.cmc === manaValue)
          .reduce((sum, rock) => sum + rock.qty, 0);
        return Math.max(0, (bucket?.count || 0) - rocksAtValue, expected);
      })
    );

    const chartRows = reference.curve
      .map((expected, index) => {
        const manaValue = index + 1;
        const bucket = stats.manaCurve.find((item) => Number(item.cmc) === manaValue);
        const rocksAtValue = manaRocks
          .filter((rock) => rock.cmc === manaValue)
          .reduce((sum, rock) => sum + rock.qty, 0);
        const current = Math.max(0, (bucket?.count || 0) - rocksAtValue);
        const diff = current - expected;
        const titleText = `MW ${manaValue}: Deck ${current}, Modell ${expected} (${diff >= 0 ? '+' : ''}${diff})`;

        return `
          <div class="advice-curve-col" title="${escapeAttr(titleText)}">
            <div class="advice-curve-pair">
              <div class="advice-curve-series">
                <span class="advice-curve-value">${current}</span>
                <div class="advice-curve-track">
                  <span class="advice-curve-bar advice-curve-bar--deck" style="height:${current / maxCount * 100}%"></span>
                </div>
              </div>
              <div class="advice-curve-series">
                <span class="advice-curve-value">${expected}</span>
                <div class="advice-curve-track">
                  <span class="advice-curve-bar advice-curve-bar--model" style="height:${expected / maxCount * 100}%"></span>
                </div>
              </div>
            </div>
            <strong class="advice-curve-mv">${manaValue}</strong>
          </div>
        `;
      })
      .join('');

    const modeledLands = stats.landArchetypes.find((item) => item.key === 'mdfc_land')?.count || 0;
    const effectiveLands = stats.manaValue.landCount + modeledLands / 2;
    const currentRocks = manaRocks.reduce((sum, rock) => sum + rock.qty, 0);

    return `
      <div class="advice-model-block" data-advice-curve-card>
        <div class="advice-model-header">
          <h4>👑 ${escapeHtml(commander.name)} (${t('an.col.mv')} ${commander.cmc}) ${colorPipBadgesHtml(commander.colorIdentity)}</h4>
          <span class="advice-status-pill advice-status-pill--info">Modell MW ${commander.cmc}</span>
        </div>
        <p class="hint">${escapeHtml(t('an.advice.modelCounts', {
          lands: fmt(effectiveLands),
          targetLands: reference.lands,
          rocks: currentRocks,
          targetRocks: reference.rocks,
        }))}</p>
        <div class="advice-curve-controls" role="group" aria-label="${escapeAttr(t('an.advice.curveViewLabel'))}">
          <button type="button" data-advice-curve-view="table" aria-pressed="true">${t('an.advice.curveViewTable')}</button>
          <button type="button" data-advice-curve-view="chart" aria-pressed="false">${t('an.advice.curveViewChart')}</button>
        </div>
        <div data-advice-curve-panel="table">
          <table class="analyze-table advice-curve-table">
            <thead>
              <tr>
                <th>${t('an.col.mv')}</th>
                <th>${t('an.advice.currentSpells')}</th>
                <th>${t('an.advice.referenceSpells')}</th>
                <th>${t('an.advice.diff')}</th>
                <th>${t('an.advice.visualRatio')}</th>
              </tr>
            </thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
        <div class="advice-curve-chart" data-advice-curve-panel="chart" hidden>
          <div class="advice-curve-legend">
            <span><i class="advice-curve-bar advice-curve-bar--deck"></i>${t('an.advice.currentSpells')}</span>
            <span><i class="advice-curve-bar advice-curve-bar--model"></i>${t('an.advice.referenceSpells')}</span>
          </div>
          <div class="advice-curve-columns">${chartRows}</div>
        </div>
      </div>
    `;
  });

  return `
    <div class="analyze-chart-card">
      <h4>${t('an.advice.curveHeading')}</h4>
      <div class="advice-callout advice-callout--${isBalanced ? 'ok' : 'warn'}">
        <span class="advice-callout-icon">${isBalanced ? '✓' : '⚠'}</span>
        <div>${escapeHtml(curveGuidance)}</div>
      </div>
      ${commanderGuides.length ? commanderGuides.join('') : `<p class="hint">${t('an.advice.noCommander')}</p>`}
      <div class="advice-caveat">
        <span class="advice-caveat-icon">ℹ</span>
        <p>${escapeHtml(t('an.advice.curveCaveat'))}</p>
      </div>
    </div>
  `;
}

function adviceManaBaseHtml(stats) {
  const mdfcCount = stats.landArchetypes.find((item) => item.key === 'mdfc_land')?.count || 0;
  const effectiveLands = stats.manaValue.landCount + mdfcCount / 2;
  const manaRocks = stats.accelerants.manaRocks;
  const rockCount = manaRocks.reduce((sum, rock) => sum + rock.qty, 0);
  const includesSolRing = manaRocks.some((rock) => rock.name.trim().toLowerCase() === 'sol ring');
  const dorkCount = stats.accelerants.manaDorks?.reduce((s, d) => s + d.qty, 0) || 0;
  const rampSpellCount = stats.accelerants.landRampSpells?.reduce((s, r) => s + r.qty, 0) || 0;

  const landAdviceItems = [];
  const rockAdviceItems = [];

  let targetLands = GUIDE_BASE_LANDS;
  let targetRocks = GUIDE_BASE_MANA_ROCKS;
  let hasCommanderRef = false;

  stats.commanders.forEach((commander) => {
    const reference = COMMANDER_CURVE_REFERENCE[commander.cmc];
    if (!reference) return;
    hasCommanderRef = true;
    targetLands = reference.lands;
    targetRocks = reference.rocks;
    const landDifference = reference.lands - effectiveLands;
    const rockDifference = reference.rocks - rockCount;

    landAdviceItems.push(
      landDifference > 0
        ? t('an.advice.landIncreaseTarget', { count: Math.ceil(landDifference), target: reference.lands })
        : t('an.advice.landAtTarget', { actual: fmt(effectiveLands), target: reference.lands })
    );

    rockAdviceItems.push(
      rockDifference > 0
        ? t('an.advice.rockIncreaseTarget', { actual: rockCount, count: rockDifference, target: reference.rocks })
        : t('an.advice.rockAtTarget', { actual: rockCount, target: reference.rocks })
    );
  });

  if (!hasCommanderRef) {
    if (includesSolRing) {
      const additionalRocks = Math.max(0, rockCount - GUIDE_BASE_MANA_ROCKS);
      const fewerLandTarget = Math.max(
        GUIDE_MIN_MIDRANGE_LANDS,
        GUIDE_BASE_LANDS - Math.floor(additionalRocks / GUIDE_ROCKS_PER_LAND_CUT.min)
      );
      const moreLandTarget = Math.max(
        GUIDE_MIN_MIDRANGE_LANDS,
        GUIDE_BASE_LANDS - Math.floor(additionalRocks / GUIDE_ROCKS_PER_LAND_CUT.max)
      );
      const targetRange = [fewerLandTarget, moreLandTarget].sort((a, b) => a - b);
      targetLands = targetRange[0];
      targetRocks = rockCount;
      landAdviceItems.push(t('an.advice.rockAdjustedLandTarget', {
        actual: fmt(effectiveLands),
        min: targetRange[0],
        max: targetRange[1],
        rocks: rockCount,
      }));
      if (effectiveLands < targetRange[0]) {
        landAdviceItems.push(t('an.advice.landIncreaseTarget', {
          count: Math.ceil(targetRange[0] - effectiveLands),
          target: targetRange[0],
        }));
      }
    } else {
      targetLands = GUIDE_BASE_LANDS;
      targetRocks = GUIDE_BASE_MANA_ROCKS;
      landAdviceItems.push(t('an.advice.landBaseline', {
        lands: GUIDE_BASE_LANDS,
        rocks: GUIDE_BASE_MANA_ROCKS,
        actualLands: fmt(effectiveLands),
        actualRocks: rockCount,
      }));
      if (effectiveLands < GUIDE_BASE_LANDS) {
        landAdviceItems.push(t('an.advice.landIncreaseTarget', {
          count: Math.ceil(GUIDE_BASE_LANDS - effectiveLands),
          target: GUIDE_BASE_LANDS,
        }));
      }
    }
  }

  if (effectiveLands < GUIDE_MIN_MIDRANGE_LANDS) {
    landAdviceItems.push(t('an.advice.landFloor', {
      actual: fmt(effectiveLands),
      floor: GUIDE_MIN_MIDRANGE_LANDS,
    }));
  }

  const totalPipDemand = Object.values(stats.colorPips.cards).reduce((sum, count) => sum + count, 0);
  const totalPotentialSources = Object.values(stats.colorPips.sources).reduce((sum, count) => sum + count, 0);

  const activeColors = Object.keys(COLOR_NAMES).filter((color) => {
    return (stats.colorPips.cards[color] || 0) > 0 || (stats.colorPips.sources[color] || 0) > 0;
  });

  const colorGaps = [];
  const colorTableRows = activeColors.map((color) => {
    const cardCount = stats.colorPips.cards[color] || 0;
    const sourceCount = stats.colorPips.sources[color] || 0;
    const demandShare = totalPipDemand ? cardCount / totalPipDemand : 0;
    const sourceShare = totalPotentialSources ? sourceCount / totalPotentialSources : 0;
    const isDeficit = demandShare > sourceShare;

    if (isDeficit) {
      colorGaps.push(
        t('an.advice.colorGap', {
          color: COLOR_NAMES[color],
          demand: fmt(demandShare * 100),
          sources: fmt(sourceShare * 100),
        })
      );
    }

    const statusPill = isDeficit
      ? `<span class="advice-status-pill advice-status-pill--warn">⚠ −${fmt((demandShare - sourceShare) * 100)}%</span>`
      : `<span class="advice-status-pill advice-status-pill--ok">✓ ${t('an.advice.colorStatusCovered')}</span>`;

    return `
      <tr>
        <td>
          <div class="advice-color-cell">
            <span class="color-pip color-pip--${COLOR_CLASS[color]}">${color}</span>
            <span>${COLOR_NAMES[color]}</span>
          </div>
        </td>
        <td>
          <div class="advice-color-bar-wrapper">
            <span>${fmt(demandShare * 100)}% <small style="color:var(--text-dim)">(${cardCount})</small></span>
            <span class="advice-color-bar-track">
              <span class="advice-color-bar-fill advice-color-bar-fill--demand" style="width:${Math.min(100, Math.round(demandShare * 100))}%"></span>
            </span>
          </div>
        </td>
        <td>
          <div class="advice-color-bar-wrapper">
            <span>${fmt(sourceShare * 100)}% <small style="color:var(--text-dim)">(${sourceCount})</small></span>
            <span class="advice-color-bar-track">
              <span class="advice-color-bar-fill advice-color-bar-fill--source" style="width:${Math.min(100, Math.round(sourceShare * 100))}%"></span>
            </span>
          </div>
        </td>
        <td>${statusPill}</td>
      </tr>
    `;
  }).join('');

  const colorReviewText = colorGaps.length
    ? t('an.advice.colorReview', { gaps: colorGaps.join('; ') })
    : t('an.advice.colorBalanced');

  return `
    <div class="analyze-chart-card">
      <h4>${t('an.advice.manaBaseHeading')} — ${t('an.manaAdvice.reference')}</h4>
      <div class="advice-mana-grid">
        <div class="advice-subcard">
          <h5>⛰ ${t('an.advice.landsSection')}</h5>
          <div class="advice-kpi-block">
            <div class="advice-kpi-row">
              <span class="advice-kpi-value">${fmt(effectiveLands)}</span>
              <span class="advice-kpi-target">Ziel: ~${targetLands}</span>
            </div>
            <div class="advice-kpi-detail">
              ${stats.manaValue.landCount} ${t('an.advice.regularLands')}${mdfcCount > 0 ? ` + ${mdfcCount} MDFCs (${fmt(mdfcCount / 2)} eff.)` : ''}
            </div>
            <div class="advice-progress-track">
              <div class="advice-progress-fill" style="width:${Math.min(100, Math.round((effectiveLands / targetLands) * 100))}%"></div>
            </div>
          </div>
          <div class="advice-kpi-block">
            <div class="advice-kpi-row">
              <span class="advice-kpi-value">${rockCount}</span>
              <span class="advice-kpi-target">Ziel: ~${targetRocks}</span>
            </div>
            <div class="advice-kpi-detail">
              ${rockCount} ${t('an.advice.manaRocksCount')} (${includesSolRing ? t('an.advice.solRingPresent') : t('an.advice.solRingMissing')})
              ${(dorkCount > 0 || rampSpellCount > 0) ? `<br><small style="color:var(--text-dim)">+ ${t('an.advice.dorksAndRamp', { dorks: dorkCount, ramp: rampSpellCount })}</small>` : ''}
            </div>
            <div class="advice-progress-track">
              <div class="advice-progress-fill" style="width:${targetRocks ? Math.min(100, Math.round((rockCount / targetRocks) * 100)) : 100}%"></div>
            </div>
          </div>
          <ul class="issue-list" style="margin:0">
            ${[...landAdviceItems, ...rockAdviceItems].map((item) => `<li>${escapeHtml(item)}</li>`).join('')}
          </ul>
        </div>

        <div class="advice-subcard">
          <h5>🎨 ${t('an.advice.colorSection')}</h5>
          ${activeColors.length ? `
            <table class="advice-color-table">
              <thead>
                <tr>
                  <th>${t('an.advice.colorTableHeaderColor')}</th>
                  <th>${t('an.advice.colorTableHeaderDemand')}</th>
                  <th>${t('an.advice.colorTableHeaderSources')}</th>
                  <th>${t('an.advice.colorTableHeaderStatus')}</th>
                </tr>
              </thead>
              <tbody>${colorTableRows}</tbody>
            </table>
          ` : `<p class="empty-state">${t('an.noCards')}</p>`}
          <div class="advice-callout advice-callout--${colorGaps.length === 0 ? 'ok' : 'warn'}">
            <span class="advice-callout-icon">${colorGaps.length === 0 ? '✓' : '⚠'}</span>
            <div>${escapeHtml(colorReviewText)}</div>
          </div>
        </div>
      </div>

      <div class="advice-caveat">
        <span class="advice-caveat-icon">ℹ</span>
        <p>${escapeHtml(t('an.advice.manaBaseCaveat', { mdfc: fmt(mdfcCount / 2) }))}</p>
      </div>
    </div>
  `;
}

function renderComboInfoPoint(combo) {
  const hasDesc = Boolean(combo.description && combo.description.trim());
  const hasReq = Boolean(combo.requirements && combo.requirements.length);
  if (!hasDesc && !hasReq) return '';

  return `
    <details class="advice-combo-info-point">
      <summary class="advice-combo-info-summary" title="${escapeAttr(t('an.advice.comboShowExplanation'))}">
        <span class="advice-info-icon" aria-hidden="true">ℹ</span>
        <span>${t('an.advice.comboExplanation')}</span>
      </summary>
      <div class="advice-combo-info-content">
        ${hasDesc ? `<p class="advice-combo-desc">${escapeHtml(combo.description)}</p>` : ''}
        ${hasReq ? `<p class="advice-combo-req"><span style="font-weight:600">${escapeHtml(t('an.advice.combosPrereq'))}:</span> ${escapeHtml(combo.requirements.join('; '))}</p>` : ''}
      </div>
    </details>
  `;
}

function relatedComboAdviceHtml(state, comboData, stats = null) {
  if (state === 'loading') {
    return `<div class="analyze-chart-card"><h4>${t('an.advice.combosHeading')}</h4><p class="empty-state"><span class="spinner" aria-hidden="true"></span>${t('an.advice.combosLoading')}</p></div>`;
  }
  if (state === 'incomplete') {
    return `<div class="analyze-chart-card"><h4>${t('an.advice.combosHeading')}</h4><p class="server-status warning">${t('an.advice.combosIncomplete')}</p></div>`;
  }
  if (state === 'error') {
    return `<div class="analyze-chart-card"><h4>${t('an.advice.combosHeading')}</h4><p class="server-status warning">${t('an.advice.combosError')}</p><button type="button" data-combo-analysis-retry>${t('an.combos.retry')}</button></div>`;
  }

  const recommendations = comboData?.recommendations || [];
  if (!recommendations.length) {
    return `<div class="analyze-chart-card"><h4>${t('an.advice.combosHeading')}</h4><p class="empty-state">${t('an.advice.combosNone')}</p></div>`;
  }

  const currentCombosCount = stats?.bracketAnalysis?.combos?.length || 0;

  // Group combos with the same "Already in deck:" cards and the same effects together
  const groups = new Map();
  for (const combo of recommendations) {
    const matchedNames = (combo.matched || [])
      .map((m) => m.name.trim())
      .sort((a, b) => a.localeCompare(b));
    const matchedKey = matchedNames.join(' + ');
    const producesList = (combo.produces || [])
      .slice()
      .sort((a, b) => a.localeCompare(b));
    const producesKey = producesList.join(' | ');
    const requirementsKey = JSON.stringify([...(combo.requirements || [])].sort());
    const groupKey = `${matchedKey}:::${producesKey}:::${requirementsKey}`;

    if (!groups.has(groupKey)) {
      groups.set(groupKey, {
        matched: combo.matched,
        produces: combo.produces,
        requirements: combo.requirements || [],
        options: [],
      });
    }
    groups.get(groupKey).options.push(combo);
  }

  const groupCards = Array.from(groups.values()).map((group) => {
    const matchedCards = group.matched
      .map((use) => `<span class="advice-card-pill advice-card-pill--matched">${cardNameHtml(use.name, use.quantity)}</span>`)
      .join(' ');
    const producesTags = group.produces?.length
      ? group.produces.map((prod) => `<span class="advice-combo-tag">${escapeHtml(prod)}</span>`).join(' ')
      : '';

    // Deduplicate options that recommend the exact same missing cards
    const deduplicatedOptions = [];
    const seenMissingKeys = new Set();
    for (const opt of group.options) {
      const missingKey = (opt.missing || [])
        .map((m) => `${m.name}:${m.quantity}`)
        .sort()
        .join(' | ');
      if (!seenMissingKeys.has(missingKey)) {
        seenMissingKeys.add(missingKey);
        deduplicatedOptions.push(opt);
      }
    }

    let optionsHtml = '';
    if (deduplicatedOptions.length === 1) {
      const opt = deduplicatedOptions[0];
      const missingCards = opt.missing
        .map((use) => `<span class="advice-card-pill advice-card-pill--missing">${cardNameHtml(use.name, use.quantity)}</span>`)
        .join(' ');
      optionsHtml = `
        <div class="advice-combo-option-row">
          <div class="advice-combo-option-header">
            <span class="advice-combo-sublabel">${t('an.advice.combosMissingCards')}:</span>
          </div>
          <div class="advice-combo-option-cards">${missingCards}</div>
          ${renderComboInfoPoint(opt)}
        </div>
      `;
    } else {
      const optionRows = deduplicatedOptions.map((opt, idx) => {
        const missingCards = opt.missing
          .map((use) => `<span class="advice-card-pill advice-card-pill--missing">${cardNameHtml(use.name, use.quantity)}</span>`)
          .join(' ');
        return `
          <div class="advice-combo-option-row">
            <div class="advice-combo-option-header">
              <span class="advice-combo-option-num">Option ${idx + 1}</span>
            </div>
            <div class="advice-combo-option-cards">${missingCards}</div>
            ${renderComboInfoPoint(opt)}
          </div>
        `;
      }).join('');

      optionsHtml = `
        <div class="advice-combo-options-list">
          <span class="advice-combo-sublabel">${t('an.advice.combosRecommendedOptions', { count: deduplicatedOptions.length })}:</span>
          <div class="advice-combo-options-grid">${optionRows}</div>
        </div>
      `;
    }

    return `
      <div class="advice-combo-card">
        <div class="advice-combo-card-header">
          <div class="advice-combo-matched-box">
            <span class="advice-combo-sublabel">${t('an.advice.combosPresentCards')}:</span>
            <div class="advice-combo-card-names">${matchedCards}</div>
          </div>
          ${group.requirements.length ? `<div class="advice-combo-prerequisites">
            <span class="advice-combo-sublabel">${escapeHtml(t('an.advice.combosPrereq'))}:</span>
            <div>${escapeHtml(group.requirements.join('; '))}</div>
          </div>` : ''}
          ${producesTags ? `<div class="advice-combo-tags">${producesTags}</div>` : ''}
        </div>
        <div class="advice-combo-card-body">
          ${optionsHtml}
        </div>
      </div>
    `;
  }).join('');

  return `
    <div class="analyze-chart-card">
      <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:0.5rem">
        <h4 style="margin:0">${t('an.advice.combosHeading')}</h4>
        <div style="display:flex;align-items:center;gap:0.4rem;flex-wrap:wrap">
          <span class="advice-status-pill advice-status-pill--ok">${t('an.advice.combosCurrentInDeck', { count: currentCombosCount })}</span>
          <span class="advice-status-pill advice-status-pill--info">${t('an.advice.combosPossibleCount', { count: recommendations.length })}</span>
        </div>
      </div>
      <p class="hint">${escapeHtml(t('an.advice.combosHint'))}</p>
      <div class="advice-combo-grid">${groupCards}</div>
    </div>
  `;
}
