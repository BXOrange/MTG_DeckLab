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

const POLL_INTERVAL_MS = 1000;

function fmt(n, digits = 1) {
  return Number(n ?? 0).toLocaleString('de-DE', { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function escapeAttr(str) {
  return String(str).replace(/'/g, '&#39;').replace(/"/g, '&quot;');
}

/**
 * @param {HTMLElement} root A mount point already attached to the page.
 * @param {{commanderText?: string, mainboardText?: string, sideboardText?: string}} deckSource
 * @param {{turn: number, withRampRealistic: number}[]} expectedManaCurve
 *   The static tab's already-computed curve (`analyzeDeck`'s
 *   `stats.expectedManaCurve`) — its `withRampRealistic` series is the
 *   reference line the simulated result is compared against.
 */
export function renderDynamicAnalysisPanel(root, deckSource, expectedManaCurve) {
  let botKinds = null;
  let numMatches = 20;
  let maxTurns = 10;
  let botKind = 'goldfish';
  let job = null; // {status, completed, total, result, error} | null
  let starting = false;
  let startError = '';

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
        <h4>Simulation</h4>
        <p class="hint">
          Spielt das Deck ${escapeHtml(String(numMatches))}× gegen einen Bot durch (bis zu
          ${escapeHtml(String(maxTurns))} Züge) und wertet den tatsächlichen Verlauf aus –
          Mittelwert ± Standardabweichung über alle Partien. Läuft im Hintergrund
          und kann je nach Partienzahl einige Sekunden bis wenige Minuten dauern.
        </p>
        ${formHtml()}
        ${job ? progressHtml() : ''}
        ${job && job.status === 'error' ? `<p class="issue-list">🛑 ${escapeHtml(job.error || 'Simulation fehlgeschlagen.')}</p>` : ''}
        ${job && job.status === 'done' && job.result ? resultHtml(job.result) : ''}
      </div>
    `;
  }

  function formHtml() {
    const options = (botKinds || [])
      .map((b) => `<option value="${escapeAttr(b.kind)}" ${b.kind === botKind ? 'selected' : ''}>${escapeHtml(b.label)}</option>`)
      .join('');
    const running = job && job.status === 'running';
    const disabled = starting || running;
    return `
      <form class="analyze-sim-form">
        <label>Anzahl Partien
          <input type="number" id="sim-num-matches" min="1" max="200" value="${numMatches}" ${disabled ? 'disabled' : ''} />
        </label>
        <label>Max. Züge pro Partie
          <input type="number" id="sim-max-turns" min="1" max="30" value="${maxTurns}" ${disabled ? 'disabled' : ''} />
        </label>
        <label>Bot
          <select id="sim-bot-kind" ${disabled ? 'disabled' : ''}>${options}</select>
        </label>
        <button type="submit" class="primary" ${disabled ? 'disabled' : ''}>
          ${running ? 'Simulation läuft …' : 'Simulation starten'}
        </button>
        ${startError ? `<p class="issue-list">🛑 ${escapeHtml(startError)}</p>` : ''}
      </form>
    `;
  }

  function progressHtml() {
    const total = Math.max(1, job.total || 1);
    const pct = Math.min(100, Math.round(((job.completed || 0) / total) * 100));
    const label = job.status === 'running' ? `${job.completed || 0} / ${job.total} Partien …` : `${job.total} Partien abgeschlossen`;
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
    const commanderTiles = Object.entries(result.commanderTurns || {})
      .map(
        ([name, stat]) => `
          <div class="analyze-stat-tile">
            <span class="analyze-stat-value">${fmt(stat.mean)} ± ${fmt(stat.stddev)}</span>
            <span class="analyze-stat-label">${escapeHtml(name)}: Zug im Spiel</span>
          </div>`
      )
      .join('');
    const aborted = result.matchesAbortedInfiniteMana || 0;
    return `
      <p class="hint">${result.matchesRun} von ${result.matchesRequested} Partien ausgewertet
        (Bot: ${escapeHtml(botLabel(result.botKind))}).</p>
      ${aborted > 0 ? infiniteManaWarningHtml(aborted, result.matchesRun) : ''}
      <div class="analyze-stat-grid">
        <div class="analyze-stat-tile">
          <span class="analyze-stat-value">${fmt(tutors.mean)} ± ${fmt(tutors.stddev)}</span>
          <span class="analyze-stat-label">Bibliothekssuchen</span>
          <span class="analyze-stat-hint">Tutoren + Fetches, pro Partie</span>
        </div>
        ${commanderTiles}
      </div>

      <h4>Mana-Potenzial &amp; -Produktion vs. statische Schätzung</h4>
      <p class="hint">
        Vergleicht die tatsächlich simulierte offene Mana-Kapazität ("Potenzial") und
        das tatsächlich verbrauchte Mana ("Produktion") pro Zug mit der statischen Kurve
        aus "Erwartete verfügbare Mana pro Zug" (Länder + Beschleuniger, realistisch).
        Schattierter Bereich = ± 1 Standardabweichung über alle Partien.
      </p>
      ${manaComparisonSvg(result.perTurn)}

      <h4>Länder gezogen (kumulativ)</h4>
      ${simpleBarChart(result.perTurn, 'lands_drawn', 'Länder')}

      <h4>Kartenvorteil</h4>
      <p class="hint">
        Gezogene Karten abzüglich der Grundlinie von einer Karte pro Zug
        (RULE 103.7a: der Startspieler setzt den ersten Zug aus) – 0 ist
        "wie erwartet", ohne Ziehungs-Effekte konstant 0.
      </p>
      ${simpleBarChart(result.perTurn, 'card_advantage', 'Kartenvorteil')}
    `;
  }

  function botLabel(kind) {
    return (botKinds || []).find((b) => b.kind === kind)?.label || kind;
  }

  // Backend guard (services/dynamic_analysis.py's `INFINITE_MANA_
  // THRESHOLD`): a match that starts producing implausible amounts of mana
  // in one turn (an infinite combo) is cut short rather than run to
  // max_turns — surfaced here so a deck with a real combo doesn't just
  // read as "normal" with a few missing turns.
  function infiniteManaWarningHtml(aborted, matchesRun) {
    return `
      <p class="issue-list">
        ⚠️ ${aborted} von ${matchesRun} Partien wurden vorzeitig abgebrochen — das Deck hat
        offenbar eine Kombination, die unbegrenzt Mana produziert. Die abgebrochenen Züge
        selbst fehlen in der Auswertung, alle vorherigen Züge derselben Partie zählen weiter.
      </p>
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
    const staticLine = perTurn.every((r) => staticByTurn.has(r.turn))
      ? `<polyline points="${perTurn.map((r, i) => `${xFor(i)},${yFor(staticByTurn.get(r.turn))}`).join(' ')}" class="chart-line chart-line--context" fill="none" stroke-dasharray="4 3" />`
      : '';

    return `
      <div class="line-legend">
        <span class="line-legend-item"><span class="line-key line-key--context"></span>Statisch erwartet (Länder + Beschleuniger)</span>
        <span class="line-legend-item"><span class="line-key line-key--info"></span>Simuliert: Mana-Potenzial</span>
        <span class="line-legend-item"><span class="line-key line-key--accent"></span>Simuliert: Mana-Produktion</span>
      </div>
      <svg viewBox="0 0 ${WIDTH} ${HEIGHT}" class="analyze-svg" role="img" aria-label="Mana-Potenzial und -Produktion pro Zug, simuliert vs. statisch erwartet">
        ${gridLines}
        <polygon points="${bandPolygon(potentialValues)}" class="chart-band--accent" style="fill:var(--info)" />
        <polygon points="${bandPolygon(producedValues)}" class="chart-band--accent" />
        ${staticLine}
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
      job = { status: 'error', completed: 0, total: job?.total || 0, error: 'Verbindung zum Server verloren.' };
      render();
      return;
    }
    job = res.data;
    render();
    if (job.status === 'running') {
      setTimeout(() => poll(jobId), POLL_INTERVAL_MS);
    }
  }

  async function start() {
    startError = '';
    starting = true;
    render();
    const res = await startDynamicAnalysis({ ...deckSource, botKind, numMatches, maxTurns });
    if (!isLive()) return;
    starting = false;
    if (!res.ok || !res.data?.jobId) {
      startError = res.data?.detail?.message || res.data?.detail || 'Simulation konnte nicht gestartet werden.';
      render();
      return;
    }
    job = { status: 'running', completed: 0, total: numMatches, result: null, error: null };
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
}
