export function createPlayerBoardRenderer({
  getView,
  getBusy,
  seatStatus,
  transport,
  t,
  escapeHtml,
  escapeAttr,
  bannerStyle,
  bannerColorLabel,
  interactivePriority,
  yieldBadgeHtml,
  priorityBadgeHtml,
  manaPoolHtml,
  manaPotentialHtml,
  lifeBox,
  playerCountersHtml,
  podGrid,
  zonesSideFor,
  getMoreBattlefield,
  objGrid,
  faceDownCardHtml,
  knownLibraryHtml,
  libraryTopHtml,
  collapsibleZoneHtml,
  zoneListHtml,
  blindSideboardHtml,
  getThreeRows,
  battlefieldHtml,
  handAreaHtml,
}) {
  function boardsHtml(live, state, byInstance, pending, seatId) {
    const boards = live
      .map((player, index) => playerBoardHtml(player, state, byInstance, pending, seatId, index, live.length))
      .join('');
    return podGrid() ? `<div class="gf-pod-grid">${boards}</div>` : boards;
  }

  function playerBoardHtml(player, state, byInstance, pending, seatId = null, index = 0, total = 1) {
    const view = getView();
    const busy = getBusy();
    const moreBattlefield = getMoreBattlefield();
    const bf = state.battlefield.filter((object) => object.controller_id === player.id);
    const isMe = seatId != null && player.id === seatId;
    const ownHand = isMe || (seatId == null && !view.observer);
    const isActive = state.active_player_id === player.id;
    const seat = seatStatus(player.id);
    const badges = [
      player.has_lost
        ? `<span class="gf-seat-badge gf-seat-out">${player.loss_reason === 'conceded' ? t('bd.seat.conceded') : t('bd.seat.out')}</span>`
        : '',
      seat?.connected === false
        ? `<span class="gf-seat-badge gf-seat-away" title="${escapeAttr(t('bd.seat.awayTitle'))}">${t('bd.seat.away')}</span>`
        : '',
    ].join('');
    const bannerCss = bannerStyle(seat?.banner_color);
    const bannerAttrs = bannerCss
      ? ` style="${escapeAttr(bannerCss)}" title="${escapeAttr(`Banner-Farbe: ${bannerColorLabel(seat.banner_color)}`)}"`
      : '';
    const holdsPriority = interactivePriority() && !state.pending_choice && !state.waiting_on_choice
      && view.priority?.player_id === player.id;
    const takebacksLeft = isMe ? view.takebacks_remaining?.[view.perspective] : undefined;
    const takebackBtn = isMe && transport.takeBack && takebacksLeft > 0
      ? `<button type="button" class="gf-banner-takeback" data-banner-takeback ${busy ? 'disabled' : ''}>${escapeHtml(t('bd.banner.takeback', { count: takebacksLeft }))}</button>`
      : '';
    const priorityBits = state.game_over
      ? takebackBtn
      : !interactivePriority()
        ? takebackBtn
        : isMe
          ? takebackBtn
          : yieldBadgeHtml(player.id);
    const upper = total > 1 && (podGrid() ? index < 2 : index < Math.floor(total / 2));
    const banner = `        <header class="gf-player-board-head${bannerCss ? ' gf-banner-tinted' : ''}"${bannerAttrs}>
          <div class="gf-banner-identity">
          <h3 title="${escapeAttr(player.name)}">${escapeHtml(player.name)}${badges}</h3>
            ${priorityBits && !moreBattlefield ? `<div class="gf-banner-priority">${priorityBits}</div>` : ''}
          </div>
          <div class="gf-banner-center">
            <div class="gf-banner-status">
              <span>${isActive ? `<span class="gf-seat-badge gf-seat-active">${t('bd.seat.active')}</span>` : ''}</span>
              <span>${priorityBadgeHtml(holdsPriority, isMe, player.name)}</span>
            </div>
          </div>
          ${priorityBits && moreBattlefield ? `<div class="gf-banner-priority gf-banner-outer-status">${priorityBits}</div>` : ''}
          <div class="gf-banner-stats">
            ${moreBattlefield ? '<div class="gf-banner-mana">' : ''}
            ${manaPoolHtml(player.mana_pool)}
            ${manaPotentialHtml(view.mana_potential?.[player.id])}
            ${moreBattlefield ? '</div>' : ''}
            ${lifeBox(t('bd.zone.life'), player.life)}
            ${moreBattlefield ? `<div class="gf-banner-extra">${playerCountersHtml(player, state)}</div>` : playerCountersHtml(player, state)}
          </div>
        </header>`;
    return `
      <section class="gf-player-board${upper ? ' gf-upper-board' : ''}${isMe ? ' gf-own-board' : ''}${seatId && !isMe ? ' gf-opponent-board' : ''}${player.has_lost ? ' gf-board-out' : ''}${moreBattlefield ? ' gf-more-battlefield' : ' gf-banner-layout'}" data-player-id="${escapeAttr(player.id)}">
        ${moreBattlefield ? '' : banner}
        <div class="gf-play gf-zones-${zonesSideFor(index, total)}">
          <aside class="gf-side">
            ${moreBattlefield ? banner : ''}
            <div class="gf-zone gf-command" aria-label="${escapeAttr(t('bd.zone.commandZone'))}">
              ${player.command.length ? objGrid(player.command, '–', byInstance, pending) : `<div class="card-grid"><div class="gf-card-slot gf-command-placeholder">${faceDownCardHtml(t('bd.zone.emptyCommand'))}</div></div>`}
            </div>
            <div class="gf-zone gf-library">
              <h4>${t('bd.zone.library')}</h4>
              <p class="library-count">${escapeHtml(t('bd.zone.libraryCount', { count: player.library_count }))}</p>
              ${knownLibraryHtml(player)}
              ${libraryTopHtml(player, byInstance, pending)}
            </div>
            ${collapsibleZoneHtml('gf-graveyard', t('bd.zone.graveyard'), `${player.id}:graveyard`, player.graveyard.length, zoneListHtml(player.graveyard, t('bd.zone.empty')))}
            ${collapsibleZoneHtml('gf-exile', t('bd.zone.exile'), `${player.id}:exile`, player.exile.length, objGrid(player.exile, t('bd.zone.empty'), byInstance, pending))}
            ${ownHand && (player.sideboard || []).length ? collapsibleZoneHtml('gf-sideboard', t('bd.zone.sideboard'), `${player.id}:sideboard`, player.sideboard.length, objGrid(player.sideboard, t('bd.zone.empty'), byInstance, pending)) : ''}
            ${blindSideboardHtml(player, state)}
          </aside>

          <div class="gf-main">
            <div class="gf-zone gf-battlefield" data-drop-zone="battlefield">
              <div class="gf-bf-head">
                <h4>Battlefield (${bf.length})</h4>
                <label class="gf-bf-toggle" title="${escapeAttr(t('bd.bf.landsOwnRowTitle'))}">
                  <input type="checkbox" class="gf-rows-toggle" ${getThreeRows() ? 'checked' : ''} />
                  ${t('bd.bf.landsOwnRow')}
                </label>

              </div>
              ${battlefieldHtml(state.battlefield, player.id, byInstance, pending)}
            </div>


            ${handAreaHtml(player, state, byInstance, pending, ownHand)}
          </div>
        </div>
      </section>`;
  }

  return { boardsHtml };
}
