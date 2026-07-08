// "Deck analysieren" tab: a static, numeric breakdown of a saved deck
// (mana curve, card types, mana value, opening-hand land odds, color
// pips vs. sources) followed by the not-yet-implemented LLM analysis
// (archetype/synergy/coherence — see backend/ToDo_Backend.md "LLM Deck
// Analysis (UC2)"), under its own "Dynamische Analyse" heading.
//
// Opened from "Decks verwalten" (savedDecksView.js)'s "Deck analysieren"
// button, mirroring how "Deck editieren" hands a saved deck to
// deckImportView.js's loadDeck(). Everything here is computed client-side
// from already-resolved card data (deckAnalysis.js) — no new backend
// endpoint.

import { parseDeckSections } from './parser.js';
import { resolveCardImages } from './cardImages.js';
import { analyzeDeck } from './deckAnalysis.js';
import { escapeHtml } from './cardTile.js';

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

const DYNAMIC_ANALYSIS_HTML = `
  <section class="analyze-section">
    <h3>Dynamische Analyse</h3>
    <p class="empty-state">
      Die automatische Deck-Analyse (Gewinnstrategien, Archetyp, Synergien,
      Kohärenz-Score) ist noch nicht implementiert.
    </p>
  </section>
`;

const COLOR_NAMES = { W: 'Weiß', U: 'Blau', B: 'Schwarz', R: 'Rot', G: 'Grün' };
const COLOR_CLASS = { W: 'w', U: 'u', B: 'b', R: 'r', G: 'g' };

/**
 * @returns {{loadDeck: (savedDeck: object) => void}} lets savedDecksView.js
 *   hand a saved deck over (id/name/commanderText/mainboardText) when its
 *   "Deck analysieren" button is clicked.
 */
export function renderAnalyzeView(container) {
  container.innerHTML = emptyShellHtml();

  let requestId = 0;

  function loadDeck(savedDeck) {
    const myRequestId = ++requestId;
    container.innerHTML = loadingShellHtml(savedDeck.name);

    const parsed = parseDeckSections({
      commanderText: savedDeck.commanderText,
      mainboardText: savedDeck.mainboardText,
    });
    const names = [...parsed.commanders, ...parsed.mainDeck].map((c) => c.name);

    resolveCardImages(names).then((resolved) => {
      if (myRequestId !== requestId) return; // superseded by a later loadDeck() call
      const stats = analyzeDeck(parsed.commanders, parsed.mainDeck, resolved);
      container.innerHTML = resultShellHtml(savedDeck.name, stats);
    });
  }

  return { loadDeck };
}

function emptyShellHtml() {
  return `
    <div class="analyze-panel">
      <h2>Deck analysieren</h2>
      <p class="empty-state">
        Kein Deck geladen – in "Decks verwalten" ein Deck auswählen und auf
        "Deck analysieren" klicken.
      </p>
    </div>
    ${DYNAMIC_ANALYSIS_HTML}
  `;
}

function loadingShellHtml(deckName) {
  return `
    <div class="analyze-panel">
      <h2>Deck analysieren</h2>
      <p class="analyze-deck-name">${escapeHtml(deckName?.trim() || 'Unbenanntes Deck')}</p>
      <p class="empty-state">Lädt Kartendaten …</p>
    </div>
    ${DYNAMIC_ANALYSIS_HTML}
  `;
}

const TOC_ENTRIES = [
  { id: 'toc-mana-curve', label: 'Manakurve' },
  { id: 'toc-expected-mana-curve', label: 'Erwartete verfügbare Mana pro Zug' },
  { id: 'toc-type-distribution', label: 'Kartentyp-Verteilung' },
  { id: 'toc-land-archetypes', label: 'Land-Archetypen' },
  { id: 'toc-color-pips', label: 'Manasymbole: Kartenbedarf vs. Manaquellen' },
  { id: 'toc-opening-hand', label: 'Starthand & Landziehungen' },
  { id: 'toc-accelerants', label: 'Erkannte Beschleuniger' },
  { id: 'toc-command-zone', label: 'Funktionale Kategorien' },
  { id: 'toc-dynamic-analysis', label: 'Dynamische Analyse' },
];

function tableOfContentsHtml() {
  const items = TOC_ENTRIES.map((e) => `<li><a href="#${e.id}">${escapeHtml(e.label)}</a></li>`).join('');
  return `
    <nav class="analyze-toc" aria-label="Inhaltsverzeichnis">
      <strong class="analyze-toc-title">Inhaltsverzeichnis</strong>
      <ul class="analyze-toc-list">${items}</ul>
    </nav>
  `;
}

function resultShellHtml(deckName, stats) {
  return `
    <div class="analyze-panel">
      <h2>Deck analysieren</h2>
      <p class="analyze-deck-name">${escapeHtml(deckName?.trim() || 'Unbenanntes Deck')}</p>
      ${commanderLineHtml(stats.commanders)}
      ${unresolvedWarningHtml(stats.unresolvedNames)}
      ${tableOfContentsHtml()}

      <section class="analyze-section">
        <h3>Statische Analyse</h3>
        <p class="hint">
          Rein numerisch, aus den Kartendaten berechnet — keine
          Bewertung von Stärke, Synergien oder Archetyp (siehe "Dynamische
          Analyse" unten). Die erwartete Mana-Kurve und die
          Beschleuniger-Erkennung sind vereinfachte Schätzungen, keine
          Simulation.
        </p>

        ${summaryTilesHtml(stats)}
        <div id="toc-mana-curve">${manaCurveSectionHtml(stats)}</div>
        <div id="toc-expected-mana-curve">${expectedManaCurveSectionHtml(stats)}</div>
        <div id="toc-type-distribution">${typeDistributionSectionHtml(stats)}</div>
        <div id="toc-land-archetypes">${landArchetypesSectionHtml(stats)}</div>
        <div id="toc-color-pips">${colorPipsSectionHtml(stats)}</div>
        <div id="toc-opening-hand">${openingHandSectionHtml(stats)}</div>
        <div id="toc-accelerants">${accelerantsSectionHtml(stats)}</div>
        <div id="toc-command-zone">${commandZoneSectionHtml(stats)}</div>
      </section>
    </div>
    <div id="toc-dynamic-analysis">${DYNAMIC_ANALYSIS_HTML}</div>
  `;
}

function commanderLineHtml(commanders) {
  if (!commanders.length) return '';
  const items = commanders
    .map((c) => {
      const pips = colorPipBadgesHtml(c.colorIdentity);
      return `<span class="analyze-commander-entry">👑 ${cardNameHtml(c.name)} (MW ${c.cmc})${pips}</span>`;
    })
    .join(' ');
  return `<p class="analyze-commander-line">${items}</p>`;
}

function unresolvedWarningHtml(names) {
  if (!names.length) return '';
  return `
    <ul class="issue-list not-found-list">
      <li>🛑 ${names.length} Karte(n) nicht gefunden, aus der Analyse ausgeschlossen:
        ${names.map(escapeHtml).join(', ')}</li>
    </ul>
  `;
}

function colorPipBadgesHtml(colors) {
  if (!colors || !colors.length) {
    return ' <span class="color-identity"><span class="color-pip color-pip--c" title="Farblos">C</span></span>';
  }
  const pips = ['W', 'U', 'B', 'R', 'G']
    .filter((c) => colors.includes(c))
    .map((c) => `<span class="color-pip color-pip--${COLOR_CLASS[c]}" title="${COLOR_NAMES[c]}">${c}</span>`)
    .join('');
  return ` <span class="color-identity">${pips}</span>`;
}

function fmt(n, digits = 1) {
  return n.toLocaleString('de-DE', { minimumFractionDigits: digits, maximumFractionDigits: digits });
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
      ${statTileHtml('Karten in der Bibliothek', librarySize)}
      ${statTileHtml('Länder', manaValue.landCount, librarySize ? `${fmt((manaValue.landCount / librarySize) * 100, 0)}%` : '')}
      ${statTileHtml('Ø Manawert (mit Ländern)', fmt(manaValue.averageWithLands))}
      ${statTileHtml('Ø Manawert (ohne Länder)', fmt(manaValue.averageWithoutLands))}
      ${statTileHtml('Gesamt-Manawert', manaValue.total)}
      ${statTileHtml('Beschleuniger', stats.openingHand.accelerantCount, 'Manarocks + -dorks + Land-Ramp')}
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
      const title = names || 'Keine Karten';
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
      <h4>Manakurve</h4>
      <p class="hint">Nichtland-Karten nach Manawert (MW). Balken zeigen die Kartenanzahl je MW.</p>
      <div class="bar-chart bar-chart--columns">${bars}</div>
      <table class="analyze-table">
        <thead><tr><th>MW</th><th>Anzahl</th><th>Karten</th></tr></thead>
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
      <h4>Erwartete verfügbare Mana pro Zug</h4>
      <p class="hint">
        Basis: deck-spezifische, fetch-bereinigte Land-Erwartung (max. 1 Landdrop/Zug). 
        Bonus von Mana-Quellen (Rocks/Dorks/Ramp): nur mit aktuellem Mana bezahlbar, ab Folgezug wirksam; Einmalige Rituale zählen nicht. 
        Zwei Beschleuniger-Kurven: „maximal" – gezogen sobald bezahlbar, gedeckelt auf bisher gesehene Karten; „realistisch" – hypergeometrisch erwartet.
      </p>
      <div class="line-legend">
        <span class="line-legend-item"><span class="line-key line-key--context"></span>Nur Länder (Zug ${last.turn}: ${fmt(last.withoutRamp)})</span>
        <span class="line-legend-item"><span class="line-key line-key--info"></span>Länder + Beschleuniger, realistisch (Zug ${last.turn}: ${fmt(last.withRampRealistic)})</span>
        <span class="line-legend-item"><span class="line-key line-key--accent"></span>Länder + Beschleuniger, maximal (Zug ${last.turn}: ${fmt(last.withRampMax)})</span>
      </div>
      ${svg}
      <table class="analyze-table">
        <thead><tr><th>Zug</th><th>Nur Länder</th><th>Mit Beschleunigern (realistisch)</th><th>Mit Beschleunigern (maximal)</th></tr></thead>
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
    <svg viewBox="0 0 ${width} ${height}" class="analyze-svg" role="img" aria-label="Erwartete verfügbare Mana pro Zug">
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
      <h4>Kartentyp-Verteilung</h4>
      <p class="hint">Eine Karte kann mehrere Typen haben (z.B. Artefaktkreatur) und zählt dann in beiden Balken.</p>
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
      <h4>Land-Archetypen</h4>
      <p class="hint">
        Heuristisch aus Typzeile/Kartentext erkannt (Fetch/Schock/Schmerz/
        Check/Fast/Slow/Kampfland/Triome/Bounce/Kreaturland/Utility/…) —
        bei ungewöhnlichen Formulierungen kann ein Land in "Sonstiges"
        landen.
      </p>
      <div class="bar-chart bar-chart--rows">${bars}</div>
      <table class="analyze-table">
        <thead><tr><th>Archetyp</th><th>Anzahl</th><th>Länder</th></tr></thead>
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
      <h4>Manasymbole: Kartenbedarf vs. Manaquellen</h4>
      <p class="hint">
        Oben je Farbe: farbige Manasymbole in den Kartenkosten (Bedarf). Unten:
        Länder/Manarocks/-dorks, die diese Farbe erzeugen können (Quellen,
        anhand der Farbidentität).
      </p>
      <div class="pip-compare-legend">
        <span class="line-legend-item"><span class="line-key line-key--solid"></span>Kartenbedarf</span>
        <span class="line-legend-item"><span class="line-key line-key--light"></span>Manaquellen</span>
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
      (t) =>
        `<tr><td>${t.turn === 1 ? '1 (Starthand)' : t.turn}</td><td>${fmt(t.withoutFetchBonus)}</td><td>${fmt(t.withFetchBonus)}</td></tr>`
    )
    .join('');

  const fetchHint = fetchCount
    ? `
      <p class="hint">
        ${fetchCount} Fetchland(s) im Deck: Jedes gezogene Fetchland zählt
        selbst bereits als Land, zieht beim Cracken aber zusätzlich ein
        weiteres Land aus der verbliebenen Bibliothek (Deck-"Thinning") –
        das erhöht die ab dann verbliebene Landdichte für spätere Züge
        leicht. Geschätzter Effekt bis Zug ${lastTurn.turn}: +${fmt(fetchBonusAtEnd, 2)}
        Länder im Schnitt (Erwartungswert-Näherung, keine Simulation).
      </p>
    `
    : '';

  return `
    <div class="analyze-chart-card">
      <h4>Starthand &amp; Landziehungen (7 Karten, aus ${librarySize} Bibliothekskarten)</h4>
      <div class="analyze-stat-grid analyze-stat-grid--compact">
        ${statTileHtml('Ø Länder in der Starthand', fmt(expectedLands))}
        ${statTileHtml('Ø Länder + Beschleuniger in der Starthand', fmt(expectedLandsPlusAccel))}
        ${statTileHtml('Länder im Deck', landCount)}
        ${statTileHtml('davon Fetchlands', fetchCount)}
        ${statTileHtml('Beschleuniger im Deck', accelerantCount)}
      </div>
      <p class="hint">Wahrscheinlichkeit für genau k Länder in der Starthand (hypergeometrisch):</p>
      <div class="prob-row">${probRow}</div>

      <p class="hint" style="margin-top:0.8rem">
        Erwartete Länder in Hand/Spiel im Zeitverlauf (kumulativ; Zug 1 =
        Starthand, danach ein Kartenzug pro Zug):
      </p>
      ${fetchHint}
      <table class="analyze-table">
        <thead><tr><th>Zug</th><th>Ø Länder ohne Fetch-Effekt</th><th>Ø Länder mit Fetch-Effekt</th></tr></thead>
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
        <h4>Erkannte Beschleuniger</h4>
        <p class="empty-state">Keine Manarocks/-dorks/Ramp-Zauber/Treasure-Generatoren erkannt.</p>
      </div>
    `;
  }
  const list = (title, items) => {
    if (!items.length) return '';
    const li = items
      .slice()
      .sort((a, b) => a.name.localeCompare(b.name))
      .map((c) => `<li>${cardNameHtml(c.name, c.qty)} <span class="accelerant-cmc">MW ${c.cmc}</span></li>`)
      .join('');
    return `<div class="accelerant-group"><strong>${title} (${items.length})</strong><ul class="card-list">${li}</ul></div>`;
  };
  return `
    <div class="analyze-chart-card">
      <h4>Erkannte Beschleuniger</h4>
      <p class="hint">
        Heuristisch aus dem Kartentext erkannt — bei ungewöhnlichen
        Formulierungen kann eine Karte fehlen oder fälschlich auftauchen.
        Nur Manarocks, -dorks, Land-Auren (z.B. Wild Growth) und Land-Ramp
        (Land-Tutoren) zählen als dauerhafte Mana-Beschleunigung (siehe
        Manakurve/Starthand oben) – Rituale (einmaliger Mana-Stoß) und
        Treasure-Generatoren (Bedingung/Trigger nötig, Token wird beim
        Nutzen verbraucht) sind nur zur Übersicht gelistet und fließen
        dort nicht mit ein.
      </p>
      <div class="accelerant-groups">
        ${list('Manarocks', manaRocks)}
        ${list('Manadorks', manaDorks)}
        ${list('Land-Auren', manaLandAuras)}
        ${list('Land-Ramp (Tutoren)', landRampSpells)}
        ${list('Rituale', rituals)}
        ${list('Treasure-Generatoren', treasureGenerators)}
      </div>
    </div>
  `;
}

// --- Command Zone deckbuilding-template categories --------------------------

function commandZoneSectionHtml(stats) {
  const { categories, targetedDisruption, massDisruption, cardAdvantage } = stats.commandZone;
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
        <thead><tr><th>Typ</th><th>Anzahl</th><th>Karten</th></tr></thead>
        <tbody>${trs}</tbody>
      </table>
    `;
  };

  return `
    <div class="analyze-chart-card">
      <h4>Funktionale Kategorien</h4>
      <p class="hint">
        Heuristische Einordnung nach Deck-Funktion, angelehnt an gängige
        Commander-Deckbau-Templates (Lands / Ramp / Card Advantage /
        Targeted Disruption / Mass Disruption / Plan Cards) — jede
        Nichtland-Karte zählt zu genau einer Kategorie (Ramp vor Mass- vor
        Targeted Disruption vor Card Advantage, der Rest zählt als Plan
        Cards). Aus dem Kartentext erkannt — bei ungewöhnlichen
        Formulierungen kann eine Karte in der falschen Kategorie landen.
      </p>
      <div class="bar-chart bar-chart--rows">${bars}</div>
      <table class="analyze-table">
        <thead><tr><th>Kategorie</th><th>Anzahl</th><th>Karten</th></tr></thead>
        <tbody>${tableRows}</tbody>
      </table>
      ${subKindTable('Card Advantage – Details', cardAdvantage)}
      ${subKindTable('Targeted Disruption – Details', targetedDisruption)}
      ${subKindTable('Mass Disruption – Details', massDisruption)}
    </div>
  `;
}
