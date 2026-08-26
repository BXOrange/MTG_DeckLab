// The end-of-match review: the per-player stats digest the server puts in
// every session view (`GameSession.analysis`, services/game_session.py).
//
// Extracted from goldfishView.js so the multiplayer summary screen shows the
// identical breakdown — same totals, same mana curve, same mana-per-turn
// bars — rather than a second, drifting copy of it.

/**
 * Totals + a mana-value curve and mana-per-turn bars for each player,
 * side by side.
 * @param {{turns: number, players: Object<string, object>}|null} analysis
 */
export function analysisHtml(analysis) {
  if (!analysis || !analysis.players) return '';
  const players = Object.values(analysis.players);
  const cards = players.map((p) => analysisCardHtml(p)).join('');
  return `
    <div class="gf-analysis">
      <h4>Auswertung nach ${analysis.turns} Zügen</h4>
      <div class="gf-analysis-grid">${cards}</div>
    </div>`;
}

function analysisCardHtml(p) {
  const stat = (label, value) =>
    `<div class="gf-stat"><span class="gf-stat-v">${value}</span><span class="gf-stat-l">${label}</span></div>`;
  return `
    <div class="gf-analysis-card">
      <h5>${p.is_dummy ? '🐟 ' : ''}${escapeHtml(p.name)}</h5>
      <div class="gf-stat-row">
        ${stat('Gezogen', p.cards_drawn)}
        ${stat('Gespielt', p.cards_played)}
        ${stat('Zauber', p.spells_cast)}
        ${stat('Länder', p.lands_played)}
      </div>
      <div class="gf-stat-row">
        ${stat('Mana erzeugt', p.mana_produced)}
        ${stat('Ø MW', p.avg_cmc)}
        ${stat('Schaden', p.damage_dealt)}
        ${stat('erhalten', p.damage_taken)}
      </div>
      ${barChartHtml('Mana-Kurve gespielter Zauber (MW)', p.cmc_curve)}
      ${barChartHtml('Mana pro Zug', p.mana_per_turn)}
    </div>`;
}

// A minimal CSS bar chart over a {key: value} map (keys sorted numerically),
// heights scaled to the largest bar. No external chart lib — inline divs.
export function barChartHtml(title, map) {
  const entries = Object.entries(map || {})
    .map(([k, v]) => [Number(k), v])
    .sort((a, b) => a[0] - b[0]);
  if (!entries.length) {
    return `<div class="gf-chart"><span class="gf-chart-title">${escapeHtml(title)}</span><p class="empty-state">—</p></div>`;
  }
  const max = Math.max(...entries.map(([, v]) => v));
  const bars = entries
    .map(([k, v]) => {
      const h = max ? Math.round((v / max) * 100) : 0;
      return `<div class="gf-bar" title="${k}: ${v}"><span class="gf-bar-v">${v}</span><span class="gf-bar-fill" style="height:${h}%"></span><span class="gf-bar-k">${k}</span></div>`;
    })
    .join('');
  return `<div class="gf-chart"><span class="gf-chart-title">${escapeHtml(title)}</span><div class="gf-bars">${bars}</div></div>`;
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str == null ? '' : String(str);
  return div.innerHTML;
}
