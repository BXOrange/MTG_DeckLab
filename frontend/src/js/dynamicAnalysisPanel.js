// ANA-4: the "Dynamische Analyse" sub-tab's content — run N headless
// goldfish matches against a bot (services/dynamic_analysis.py) and show
// turn-by-turn stats — mean ± standard deviation — including a chart
// comparing the simulated mana potential/production against the static
// "Erwartete verfügbare Mana pro Zug" estimate (deckAnalysis.js's
// `simulateManaCurve`, plotted in analyzeView.js's static tab) in one
// shared graph. This *is* "Dynamische Analyse" — deliberately not a
// separate "Simulation" tab sitting next to it (an earlier cut had both;
// merged on request, since a second, still-empty tab right beside a
// working one only read as broken).
//
// Mounted by analyzeView.js *after* it sets `resultShellHtml`'s markup
// (the same way it calls `wireAnalyzeTabs` post-innerHTML) — a placeholder
// `<div>` there is handed to `renderDynamicAnalysisPanel` as `root`.

import { fetchBotKinds, getDynamicAnalysisJob, startDynamicAnalysis } from './api.js';
import { escapeHtml } from './cardTile.js';
import { t, tPlural, fmtNumber } from './i18n.js';

const POLL_INTERVAL_MS = 1000;

function fmt(n, digits = 1) {
  return fmtNumber(n, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function escapeAttr(str) {
  return String(str).replace(/'/g, '&#39;').replace(/"/g, '&quot;');
}

/**
 * @param {HTMLElement} root A mount point already attached to the page.
 * @param {{commanderText?: string, mainboardText?: string, sideboardText?: string, favoriteCards?: string[]}} deckSource
 * @param {{turn: number, withRampRealistic: number}[]} expectedManaCurve
 *   The static tab's already-computed curve (`analyzeDeck`'s
 *   `stats.expectedManaCurve`) — its `withRampRealistic` series is the
 *   reference line the simulated result is compared against.
 */
export function renderDynamicAnalysisPanel(root, deckSource, expectedManaCurve, initialComboState = 'loading') {
  let botKinds = null;
  let numMatches = 20;
  let maxTurns = 10;
  let botKind = 'smart';
  let job = null; // {status, completed, total, result, error} | null
  let starting = false;
  let startError = '';
  let combos = [];
  let comboState = initialComboState;

  // A container that's been replaced (a different deck was loaded — see
  // analyzeView.js's `loadDeck`, which reassigns `container.innerHTML`
  // wholesale) is detached from the page; a stray poll callback checks
  // this before touching anything so it can't paint over a newer panel.
  const isLive = () => document.body.contains(root);

  function render() {
    if (!isLive()) return;
    root.innerHTML = panelHtml();
    wire();
  }

  function panelHtml() {
    return `
      <div class="analyze-chart-card">
        <h4>${t('dyn.simulation')}</h4>
        <p class="hint">${escapeHtml(t('dyn.intro', { matches: numMatches, turns: maxTurns }))}</p>
        ${formHtml()}
        ${job ? progressHtml() : ''}
        ${job && job.status === 'error' ? `<p class="issue-list">🛑 ${escapeHtml(job.error || t('dyn.failedGeneric'))}</p>` : ''}
        ${job && job.status === 'done' && job.result ? resultHtml(job.result) : ''}
      </div>
    `;
  }

  function formHtml() {
    const options = (botKinds || [])
      .map((b) => `<option value="${escapeAttr(b.kind)}" ${b.kind === botKind ? 'selected' : ''}>${escapeHtml(b.label)}</option>`)
      .join('');
    // "queued": the backend's bounded worker pool (config.py's
    // MTG_DYNAMIC_ANALYSIS_WORKERS) hasn't picked this job up yet — still
    // in progress from the UI's perspective, just not running matches yet.
    const inProgress = job && (job.status === 'running' || job.status === 'queued');
    const waitingForCombos = comboState === 'loading';
    const disabled = starting || inProgress || waitingForCombos;
    return `
      <form class="analyze-sim-form">
        <label>${t('dyn.numMatches')}
          <input type="number" id="sim-num-matches" min="1" max="200" value="${numMatches}" ${disabled ? 'disabled' : ''} />
        </label>
        <label>${t('dyn.maxTurns')}
          <input type="number" id="sim-max-turns" min="1" max="30" value="${maxTurns}" ${disabled ? 'disabled' : ''} />
        </label>
        <label>${t('dyn.bot')}
          <select id="sim-bot-kind" ${disabled ? 'disabled' : ''}>${options}</select>
        </label>
        <button type="submit" class="primary" ${disabled ? 'disabled' : ''}>
          ${waitingForCombos ? t('dyn.combosLoading') : job && job.status === 'queued' ? t('dyn.waitingWorker') : inProgress ? t('dyn.running') : t('dyn.start')}
        </button>
        ${waitingForCombos ? `<p class="hint">${escapeHtml(t('dyn.combosLoadingHint'))}</p>` : ''}
        ${startError ? `<p class="issue-list">🛑 ${escapeHtml(startError)}</p>` : ''}
      </form>
    `;
  }

  function progressHtml() {
    const total = Math.max(1, job.total || 1);
    const pct = Math.min(100, Math.round(((job.completed || 0) / total) * 100));
    const label =
      job.status === 'queued'
        ? t('dyn.waitingWorker')
        : job.status === 'running'
          ? t('dyn.progressRunning', { done: job.completed || 0, total: job.total })
          : t('dyn.progressDone', { total: job.total });
    return `
      <div class="bar-row">
        <span class="bar-row-label">${escapeHtml(label)}</span>
        <div class="bar-row-track"><div class="bar-row-fill" style="width:${pct}%"></div></div>
        <span class="bar-row-value">${pct}%</span>
      </div>
    `;
  }

  function resultHtml(result) {
    const tutors = result.tutorsResolved;
    const mulligans = result.mulligansTaken;
    const mulliganDistribution = Object.entries(result.mulliganDistribution || {})
      .sort(([a], [b]) => Number(a) - Number(b))
      .map(([count, matches]) =>
        tPlural('dyn.mulliganDistributionEntry', Number(count), {
          matches: tPlural('dyn.mulliganMatches', matches),
        })
      )
      .join(' · ');
    const commanderTiles = Object.entries(result.commanderTurns || {})
      .map(
        ([name, stat]) => `
          <div class="analyze-stat-tile">
            <span class="analyze-stat-value">${fmt(stat.mean)} ± ${fmt(stat.stddev)}</span>
            <span class="analyze-stat-label">${escapeHtml(t('dyn.commanderTurnLabel', { name }))}</span>
          </div>`
      )
      .join('');
    const aborted = result.matchesAbortedInfiniteMana || 0;
    return `
      <p class="hint">${escapeHtml(t('dyn.matchesEvaluated', { run: result.matchesRun, requested: result.matchesRequested, bot: botLabel(result.botKind) }))}</p>
      ${aborted > 0 ? infiniteManaWarningHtml(aborted, result.matchesRun, result.infiniteManaTurn) : ''}
      <div class="analyze-stat-grid">
        <div class="analyze-stat-tile">
          <span class="analyze-stat-value">${fmt(tutors.mean)} ± ${fmt(tutors.stddev)}</span>
          <span class="analyze-stat-label">${t('dyn.tutors')}</span>
          <span class="analyze-stat-hint">${t('dyn.tutorsHint')}</span>
        </div>
        <div class="analyze-stat-tile">
          <span class="analyze-stat-value">${fmt(mulligans.mean)} ± ${fmt(mulligans.stddev)}</span>
          <span class="analyze-stat-label">${t('dyn.mulligans')}</span>
          <span class="analyze-stat-hint">${escapeHtml(t('dyn.mulliganHint', { distribution: mulliganDistribution }))}</span>
        </div>
        ${commanderTiles}
      </div>

      ${favoriteCardsHtml(result.favoriteCards)}
      ${comboStatsHtml(result.comboStats, result.anyComboStats)}

      <h4>${t('dyn.manaComparisonHeading')}</h4>
      <p class="hint">${escapeHtml(t('dyn.manaComparisonHint'))}</p>
      ${manaComparisonSvg(result.perTurn)}

      <h4>${t('dyn.landsDrawnHeading')}</h4>
      ${simpleBarChart(result.perTurn, 'lands_drawn', t('dyn.lands'))}

      <h4>${t('dyn.cardAdvantageHeading')}</h4>
      <p class="hint">${escapeHtml(t('dyn.cardAdvantageHint'))}</p>
      ${simpleBarChart(result.perTurn, 'card_advantage', t('dyn.cardAdvantage'))}
    `;
  }

  // Favorite cards are starred in Deck-Edit-Mode (deckImportView.js,
  // Deck.favoriteCards) and threaded into `startDynamicAnalysis`'s request
  // via `deckSource.favoriteCards` (see analyzeView.js's `loadDeck`); the
  // backend tracks per-match drawn/cast/castable turns
  // (services/dynamic_analysis.py) and this renders the aggregated
  // fractions. Empty when the deck has no starred cards.
  function favoriteCardsHtml(favoriteCards) {
    const entries = Object.entries(favoriteCards || {});
    if (!entries.length) return '';
    const rows = entries
      .map(([name, stat]) => {
        const castLabel = stat.castTurn?.n
          ? t('dyn.castTurnLabel', { pct: Math.round(stat.castFraction * 100), turn: fmt(stat.castTurn.mean) })
          : `${Math.round(stat.castFraction * 100)}%`;
        return `
          <tr>
            <td data-hover-card="${escapeAttr(name)}">${escapeHtml(name)}</td>
            <td>${Math.round(stat.drawnFraction * 100)}%</td>
            <td>${castLabel}</td>
            <td>${Math.round(stat.castableButNeverCastFraction * 100)}%</td>
          </tr>
        `;
      })
      .join('');
    return `
      <h4>${t('dyn.favoritesHeading')}</h4>
      <p class="hint">${escapeHtml(t('dyn.favoritesHint'))}</p>
      <table class="analyze-table">
        <thead><tr><th>${t('dyn.favCard')}</th><th>${t('dyn.favDrawn')}</th><th>${t('dyn.favPlayed')}</th><th>${t('dyn.favPlayableNotPlayed')}</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    `;
  }

  function comboStatsHtml(comboStats, anyCombo) {
    const entries = comboStats || [];
    if (!entries.length) {
      const message = comboState === 'error'
        ? t('dyn.combosUnavailable')
        : comboState === 'incomplete'
          ? t('dyn.combosIncomplete')
          : t('dyn.noCombos');
      return `<h4>${t('dyn.combosHeading')}</h4><p class="empty-state">${escapeHtml(message)}</p>`;
    }
    const rows = entries.map((combo) => {
      const cards = combo.uses
        .map((use) => `${escapeHtml(use.name)}${use.quantity > 1 ? ` ×${use.quantity}` : ''}`)
        .join(' + ');
      const turn = combo.assembledTurn?.n
        ? t('dyn.comboTurnLabel', {
            pct: Math.round(combo.assembledFraction * 100),
            turn: fmt(combo.assembledTurn.mean),
          })
        : t('dyn.comboNeverAssembled');
      return `<tr><td>${cards}</td><td>${escapeHtml(turn)}</td></tr>`;
    }).join('');
    return `
      <h4>${t('dyn.combosHeading')}</h4>
      <p class="hint">${escapeHtml(t('dyn.combosHint'))}</p>
      <div class="analyze-stat-tile">
        <span class="analyze-stat-value">${anyCombo?.assembledTurn?.n
          ? t('dyn.anyComboTurnLabel', {
              pct: Math.round(anyCombo.assembledFraction * 100),
              turn: fmt(anyCombo.assembledTurn.mean),
            })
          : t('dyn.anyComboNeverAssembled')}</span>
        <span class="analyze-stat-label">${t('dyn.anyComboLabel')}</span>
      </div>
      <table class="analyze-table">
        <thead><tr><th>${t('dyn.comboCards')}</th><th>${t('dyn.comboAssembly')}</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    `;
  }

  function botLabel(kind) {
    return (botKinds || []).find((b) => b.kind === kind)?.label || kind;
  }

  // Backend guard (services/dynamic_analysis.py's `INFINITE_MANA_
  // THRESHOLD`): a match that starts producing implausible amounts of mana
  // in one turn (an infinite combo) is cut short rather than run to
  // max_turns — surfaced here so a deck with a real combo doesn't just
  // read as "normal" with a few missing turns. `infiniteManaTurn` (mean ±
  // stddev across just the aborted matches) turns that into "usually goes
  // off around turn N" rather than a bare yes/no.
  function infiniteManaWarningHtml(aborted, matchesRun, infiniteManaTurn) {
    const turnHint =
      infiniteManaTurn && infiniteManaTurn.n > 0
        ? t('dyn.infiniteManaTurnHint', { mean: fmt(infiniteManaTurn.mean), stddev: fmt(infiniteManaTurn.stddev) })
        : '';
    return `
      <p class="issue-list">${escapeHtml(t('dyn.infiniteManaWarn', { aborted, run: matchesRun, turnHint }))}</p>
    `;
  }

  // -- Charts ------------------------------------------------------------

  const WIDTH = 560;
  const HEIGHT = 200;
  const PAD = { top: 16, right: 16, bottom: 26, left: 32 };
  const PLOT_W = WIDTH - PAD.left - PAD.right;
  const PLOT_H = HEIGHT - PAD.top - PAD.bottom;

  function manaComparisonSvg(perTurn) {
    const n = perTurn.length;
    const staticByTurn = new Map((expectedManaCurve || []).map((p) => [p.turn, p.withRampRealistic]));
    const maxY = Math.max(
      1,
      ...perTurn.map((r) => r.mana_potential.mean + r.mana_potential.stddev),
      ...perTurn.map((r) => r.mana_produced.mean + r.mana_produced.stddev),
      ...(expectedManaCurve || []).map((p) => p.withRampRealistic)
    );
    const xFor = (i) => PAD.left + (n > 1 ? (i / (n - 1)) * PLOT_W : 0);
    const yFor = (v) => PAD.top + PLOT_H - (v / maxY) * PLOT_H;

    const gridSteps = 4;
    const gridLines = Array.from({ length: gridSteps + 1 }, (_, i) => {
      const value = Math.round((maxY * i) / gridSteps);
      const y = yFor(value);
      return `
        <line x1="${PAD.left}" y1="${y}" x2="${WIDTH - PAD.right}" y2="${y}" class="chart-gridline" />
        <text x="${PAD.left - 6}" y="${y + 3}" class="chart-axis-text" text-anchor="end">${value}</text>
      `;
    }).join('');
    const xLabels = perTurn
      .map((r, i) => `<text x="${xFor(i)}" y="${HEIGHT - 8}" class="chart-axis-text" text-anchor="middle">${r.turn}</text>`)
      .join('');

    // Walk forward along the upper (mean + stddev) bound then back along
    // the lower (mean - stddev) bound to close one filled band shape —
    // the same idea a stacked-area chart uses.
    const bandPolygon = (values) => {
      const upper = values.map((v, i) => `${xFor(i)},${yFor(v.mean + v.stddev)}`);
      const lower = values
        .slice()
        .reverse()
        .map((v, i) => `${xFor(n - 1 - i)},${yFor(Math.max(0, v.mean - v.stddev))}`);
      return [...upper, ...lower].join(' ');
    };

    const line = (values, cls) =>
      `<polyline points="${values.map((v, i) => `${xFor(i)},${yFor(v.mean)}`).join(' ')}" class="${cls}" fill="none" />`;
    const dots = (values, cls) =>
      values.map((v, i) => `<circle cx="${xFor(i)}" cy="${yFor(v.mean)}" r="3" class="${cls}" />`).join('');

    const potentialValues = perTurn.map((r) => r.mana_potential);
    const producedValues = perTurn.map((r) => r.mana_produced);
    const staticPoints = perTurn
      .map((r, i) => staticByTurn.has(r.turn) ? `${xFor(i)},${yFor(staticByTurn.get(r.turn))}` : null)
      .filter((point) => point !== null);
    const staticDots = perTurn
      .map((r, i) => staticByTurn.has(r.turn)
        ? `<circle cx="${xFor(i)}" cy="${yFor(staticByTurn.get(r.turn))}" r="3" class="chart-dot chart-dot--context" />`
        : '')
      .join('');
    const staticLine = staticPoints.length
      ? `<polyline points="${staticPoints.join(' ')}" class="chart-line chart-line--context" fill="none" stroke-dasharray="4 3" />`
      : '';

    return `
      <div class="line-legend">
        <span class="line-legend-item"><span class="line-key line-key--context"></span>${t('dyn.legendStatic')}</span>
        <span class="line-legend-item"><span class="line-key line-key--info"></span>${t('dyn.legendPotential')}</span>
        <span class="line-legend-item"><span class="line-key line-key--accent"></span>${t('dyn.legendProduction')}</span>
      </div>
      <svg viewBox="0 0 ${WIDTH} ${HEIGHT}" class="analyze-svg" role="img" aria-label="${escapeAttr(t('dyn.svgAria'))}">
        ${gridLines}
        <polygon points="${bandPolygon(potentialValues)}" class="chart-band--accent" style="fill:var(--info)" />
        <polygon points="${bandPolygon(producedValues)}" class="chart-band--accent" />
        ${staticLine}
        ${staticDots}
        ${line(potentialValues, 'chart-line chart-line--info')}
        ${line(producedValues, 'chart-line chart-line--accent')}
        ${dots(potentialValues, 'chart-dot chart-dot--info')}
        ${dots(producedValues, 'chart-dot chart-dot--accent')}
        ${xLabels}
      </svg>
    `;
  }

  function simpleBarChart(perTurn, metric, label) {
    const values = perTurn.map((r) => r[metric].mean);
    const max = Math.max(...values.map(Math.abs), 1);
    const bars = perTurn
      .map((r) => {
        const v = r[metric].mean;
        const px = Math.round((Math.abs(v) / max) * 130);
        return `
          <div class="bar-col">
            <span class="bar-value">${fmt(v, v % 1 === 0 ? 0 : 1)}</span>
            <div class="bar-col-track">
              <div class="bar-col-fill" style="height:${px}px" title="${escapeAttr(`${label} Zug ${r.turn}: ${fmt(v)} ± ${fmt(r[metric].stddev)}`)}"></div>
            </div>
            <span class="bar-col-label">${r.turn}</span>
          </div>
        `;
      })
      .join('');
    return `<div class="bar-chart bar-chart--columns">${bars}</div>`;
  }

  // -- Networking ----------------------------------------------------------

  async function loadBotKinds() {
    const res = await fetchBotKinds();
    if (!isLive()) return;
    botKinds = res.ok ? res.data?.bots || [] : [];
    if (botKinds.length && !botKinds.some((b) => b.kind === botKind)) botKind = botKinds[0].kind;
    render();
  }

  async function poll(jobId) {
    if (!isLive()) return;
    const res = await getDynamicAnalysisJob(jobId);
    if (!isLive()) return;
    if (!res.ok || !res.data) {
      job = { status: 'error', completed: 0, total: job?.total || 0, error: t('dyn.connectionLost') };
      render();
      return;
    }
    job = res.data;
    render();
    if (job.status === 'running' || job.status === 'queued') {
      setTimeout(() => poll(jobId), POLL_INTERVAL_MS);
    }
  }

  async function start() {
    startError = '';
    starting = true;
    render();
    const res = await startDynamicAnalysis({
      ...deckSource,
      botKind,
      numMatches,
      maxTurns,
      combos: combos.map(({ id, uses }) => ({
        id,
        uses: uses.map(({ name, quantity }) => ({ name, quantity })),
      })),
    });
    if (!isLive()) return;
    starting = false;
    if (!res.ok || !res.data?.jobId) {
      startError = res.data?.detail?.message || res.data?.detail || t('dyn.couldNotStart');
      render();
      return;
    }
    // Optimistic initial state — the real status (possibly still "queued"
    // behind the backend's bounded worker pool) arrives on the first poll.
    job = { status: 'queued', completed: 0, total: numMatches, result: null, error: null };
    render();
    setTimeout(() => poll(res.data.jobId), POLL_INTERVAL_MS);
  }

  function wire() {
    root.querySelector('.analyze-sim-form')?.addEventListener('submit', (e) => {
      e.preventDefault();
      numMatches = Math.min(200, Math.max(1, Number(root.querySelector('#sim-num-matches')?.value) || numMatches));
      maxTurns = Math.min(30, Math.max(1, Number(root.querySelector('#sim-max-turns')?.value) || maxTurns));
      botKind = root.querySelector('#sim-bot-kind')?.value || botKind;
      start();
    });
  }

  render();
  if (botKinds === null) loadBotKinds();
  return {
    setCombos(nextCombos, status = 'ready') {
      combos = nextCombos || [];
      comboState = status;
      render();
    },
  };
}
