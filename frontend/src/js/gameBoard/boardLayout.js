// Clockwise pod order; keep aligned with the `.gf-pod-grid` CSS placement.
const POD_COLUMNS = ['left', 'right', 'right', 'left'];

export function boardOrder(players, seatId) {
  const live = players.filter((player) => !player.is_dummy);
  const mine = live.findIndex((player) => player.id === seatId);
  if (mine < 0) return live;
  return live.slice(mine + 1).concat(live.slice(0, mine + 1));
}

export function createBoardLayout({ getView, podGridMedia, getZonesInside }) {
  function podGrid() {
    if (podGridMedia && !podGridMedia.matches) return false;
    return (getView()?.state?.players || []).filter((player) => !player.is_dummy).length >= 3;
  }

  function zonesSideFor(index, total) {
    const zonesInside = getZonesInside();
    if (!podGrid()) return zonesInside ? 'left' : 'right';
    const spansTheRow = total % 2 === 1 && index === total - 1;
    const leftColumn = spansTheRow || POD_COLUMNS[index] === 'left';
    return zonesInside === leftColumn ? 'right' : 'left';
  }

  return { podGrid, zonesSideFor };
}

export function planechaseHtml(state, actions, { t, escapeHtml, escapeAttr, renderOracleText }) {
  const plane = state.active_plane;
  if (!plane) return '';
  const roll = (actions || []).find((action) => action.type === 'roll_planar_die');
  const rollButton = roll
    ? `<button type="button" class="primary" data-action='${escapeAttr(JSON.stringify({ type: 'roll_planar_die' }))}' title="${escapeAttr(t('bd.planar.rollTitle'))}">${renderOracleText(t('bd.planar.rollButton', { cost: roll.cost_label || '{0}' }))}</button>`
    : '';
  return `
      <div class="gf-planechase">
        <div class="gf-planechase-plane">
          <span class="gf-planechase-label" title="Aktive Ebene (Regel 901.7)">🌌 Ebene</span>
          <!-- Deliberately no data-hover-card: a plane is not in the card
               cache at all (the bulk importer drops the "planar" layout), so
               a hover lookup by name could only ever miss. Note: no
               backticks in here — this comment sits inside a template
               literal, where one would end the string mid-comment. -->
          <strong title="${escapeAttr(plane.type_line || '')}">${escapeHtml(plane.name)}</strong>
          <span class="gf-planechase-count" title="${escapeAttr(t('bd.planar.remaining'))}">${escapeHtml(t('bd.planar.inStack', { count: state.planar_deck_count || 0 }))}</span>
        </div>
        ${rollButton}
      </div>`;
}
