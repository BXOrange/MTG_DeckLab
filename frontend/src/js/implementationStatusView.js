// "Status" tab: a compact overview of what's implemented, structured two
// levels deep — top-level by software feature/use-case (docs/requirements/
// 02_MVP_USECASES_REVISED.md's UC1–UC5), then within the engine-heavy
// Goldfisch-Modus feature by the *official Comprehensive Rules chapter*
// (1 Game Concepts, 3 Card Types, 4 Zones, 5 Turn Structure, 6 Spells/
// Abilities/Effects, 7 Additional Rules, 9 Casual Variants) rather than an
// ad hoc topic grouping — mirrors docs/Reference/rules_wiki/'s own rule#
// index. Static content (no server call); kept in sync by hand with the
// backend — see CLAUDE.md "Implementation state". Deliberately heading-
// level only (no per-item prose) — see docs/implementation-state/
// Done_Backend.md / docs/implementation-state/BACKLOG.md for the full narrative.
//
// The one live, server-fetched piece on this otherwise-static tab is the
// "Abdeckung nach Set" table at the bottom — a plain data table (no card
// art/set-symbol miniatures) grouping the same per-card coverage verdict
// `cachedCardsView.js` shows per card by `Card.set_code` instead
// (GET /api/cards/coverage-by-set). Lazy-loaded on first view like
// `cachedCardsView.js`'s own `view-shown` idiom, since the tab may never be
// opened in a given session.

import { listCoverageBySet } from './api.js';
import { escapeHtml } from './cardTile.js';
import { t, getLang } from './i18n.js';
import GROUPS_DE from './locales/content/status.de.js';
import GROUPS_EN from './locales/content/status.en.js';

const LEGEND = [
  ['full', '✅', t('status.legend.full')],
  ['partial', '◐', t('status.legend.partial')],
  ['planned', '✖', t('status.legend.planned')],
];

// section = { title?, rule?, items: [ [status, label] ] } — title/rule
// omitted when a chapter/group has only one, self-explanatory section.
// chapter = { title, rule, sections: [section, …] } — one CR chapter.
// group = { title, uc?, sections: [section, …] } XOR { title, uc?, chapters: [chapter, …] }
// The feature tree is localized content (locales/content/status.<lang>.js)
// rather than t()-keyed strings — it is a document, not UI chrome.
const GROUPS = getLang() === 'de' ? GROUPS_DE : GROUPS_EN;

function statusMeta(status) {
  return LEGEND.find((l) => l[0] === status) || LEGEND[0];
}

function itemHtml([status, label]) {
  const [, icon, name] = statusMeta(status);
  return `
    <li class="impl-item impl-${status}">
      <span class="impl-badge" title="${name}">${icon}</span>
      <span class="impl-text"><strong>${label}</strong></span>
    </li>`;
}

function sectionHtml(section) {
  return `
    <section class="impl-section">
      ${
        section.title
          ? `<div class="impl-section-head">
               <h3>${section.title}</h3>
               ${section.rule ? `<span class="impl-rule">${section.rule}</span>` : ''}
             </div>`
          : ''
      }
      <ul class="impl-list">${section.items.map(itemHtml).join('')}</ul>
    </section>`;
}

function chapterHtml(chapter) {
  return `
    <div class="impl-chapter">
      <div class="impl-chapter-head">
        <h4>${chapter.title}</h4>
        ${chapter.rule ? `<span class="impl-rule">${chapter.rule}</span>` : ''}
      </div>
      <div class="impl-grid">${chapter.sections.map(sectionHtml).join('')}</div>
    </div>`;
}

function groupHtml(group) {
  const inner = group.chapters
    ? group.chapters.map(chapterHtml).join('')
    : `<div class="impl-grid">${group.sections.map(sectionHtml).join('')}</div>`;
  return `
    <div class="impl-group">
      <div class="impl-group-head">
        <h3>${group.title}</h3>
        ${group.uc ? `<span class="impl-uc">${group.uc}</span>` : ''}
      </div>
      ${inner}
    </div>`;
}

// Coverage-fraction thresholds reused from the impl-item status colors
// above, purely for a quick visual scan — a set isn't "full"/"partial"/
// "planned" in the same sense a feature row is, but the same three-tier
// green/amber/dim palette reads the same way here.
const COVERAGE_HIGH_THRESHOLD = 0.66;
const COVERAGE_LOW_THRESHOLD = 0.33;

function coverageTier(fraction) {
  if (fraction >= COVERAGE_HIGH_THRESHOLD) return 'impl-full';
  if (fraction >= COVERAGE_LOW_THRESHOLD) return 'impl-partial';
  return 'impl-planned';
}

function coverageBySetTableHtml(rows) {
  if (!rows.length) {
    return '<p class="empty-state">Keine Karten im Cache.</p>';
  }
  const body = rows
    .map((row) => {
      const pct = row.total ? (row.covered / row.total) * 100 : 0;
      return `
        <tr>
          <td>${escapeHtml(row.setCode.toUpperCase())}</td>
          <td>${row.total}</td>
          <td>${row.covered}</td>
          <td class="${coverageTier(row.fraction)}">${pct.toFixed(1)} %</td>
        </tr>`;
    })
    .join('');
  return `
    <div class="coverage-set-table-wrap">
      <table class="coverage-set-table">
        <thead>
          <tr><th>${t('status.col.set')}</th><th>${t('status.col.cards')}</th><th>${t('status.col.covered')}</th><th>${t('status.col.share')}</th></tr>
        </thead>
        <tbody>${body}</tbody>
      </table>
    </div>`;
}

export function renderImplementationStatusView(container) {
  const legend = LEGEND.map(
    ([status, icon, name]) =>
      `<span class="impl-legend-item impl-${status}"><span class="impl-badge">${icon}</span> ${name}</span>`
  ).join('');

  container.innerHTML = `
    <div class="impl-status">
      <h2>${t('status.title')}</h2>
      <p class="hint">${escapeHtml(t('status.hint'))}</p>
      <div class="impl-legend">${legend}</div>
      ${GROUPS.map(groupHtml).join('')}
      <div class="impl-group">
        <div class="impl-group-head">
          <h3>${t('status.coverageBySet')}</h3>
        </div>
        <p class="hint">${escapeHtml(t('status.coverageBySetHint'))}</p>
        <div id="coverage-by-set-result"><p class="empty-state"><span class="spinner" aria-hidden="true"></span>${t('status.loadingCoverage')}</p></div>
      </div>
    </div>`;

  const resultEl = container.querySelector('#coverage-by-set-result');

  // Only load the first time this tab is shown, not eagerly at startup —
  // matches cachedCardsView.js's own view-shown idiom. `loaded` only latches
  // on success: a failed fetch left it stuck forever (view-shown fires again
  // on every tab switch, but the guard silently ate every retry), so the
  // error state also gets its own inline retry button rather than relying on
  // "switch tabs away and back" as an undocumented workaround.
  let loaded = false;
  function loadCoverageBySet() {
    resultEl.innerHTML = `<p class="empty-state"><span class="spinner" aria-hidden="true"></span>${t('status.loadingCoverage')}</p>`;
    listCoverageBySet().then((rows) => {
      if (rows === null) {
        resultEl.innerHTML =
          `<p class="server-status warning">${t('common.serverUnreachable')}</p>` +
          `<button type="button" id="coverage-by-set-retry">${t('status.retry')}</button>`;
        resultEl.querySelector('#coverage-by-set-retry').addEventListener('click', loadCoverageBySet);
        return;
      }
      loaded = true;
      resultEl.innerHTML = coverageBySetTableHtml(rows);
    });
  }
  container.addEventListener('view-shown', () => {
    if (loaded) return;
    loadCoverageBySet();
  });
}
