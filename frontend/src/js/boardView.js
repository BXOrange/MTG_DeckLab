import { getState, setState, subscribe } from './state.js';
import { mulligan, drawCard, moveToBattlefield } from './boardEngine.js';

export function renderBoardView(container) {
  container.innerHTML = `<div id="board-root"></div>`;
  const root = container.querySelector('#board-root');

  // Local to this view (not global app state) — a plain UI preference,
  // not something a deck/board reload should reset. Read fresh by
  // `render()` below on every call, so toggling it doesn't need its own
  // re-render path separate from the existing state-change subscription.
  let hoverDetailEnabled = true;

  function render() {
    renderBoard(root, {
      hoverDetailEnabled,
      onToggleHoverDetail: (checked) => {
        hoverDetailEnabled = checked;
        render();
      },
    });
  }

  render();
  subscribe(render);
}

function renderBoard(root, { hoverDetailEnabled, onToggleHoverDetail }) {
  const { deck, board, imageCache } = getState();

  if (!deck || !board) {
    root.innerHTML = `<p class="empty-state">Noch kein Deck geladen. Importiere zuerst eine Deckliste.</p>`;
    return;
  }

  root.innerHTML = `
    <div class="board">
      <section class="zone-row opponent-row">
        ${zonePlaceholder('Gegner: Bibliothek')}
        ${zonePlaceholder('Gegner: Battlefield', true)}
        ${zonePlaceholder('Gegner: Friedhof')}
        ${lifeBox('Gegner', 40)}
      </section>

      <section class="zone-row stack-row">
        <div class="zone stack-zone">
          <h3>Stack</h3>
          <p class="empty-state">leer</p>
        </div>
      </section>

      <section class="zone-row player-battlefield-row">
        <div class="zone battlefield-zone">
          <h3>Battlefield</h3>
          ${cardGrid(board.battlefield, { empty: 'Keine Permanents', imageCache, hoverDetailEnabled })}
        </div>
      </section>

      <section class="zone-row player-meta-row">
        <div class="zone command-zone">
          <h3>Command Zone</h3>
          ${cardGrid(board.commandZone, { empty: '–', imageCache, hoverDetailEnabled })}
        </div>
        <div class="zone graveyard-zone">
          <h3>Friedhof (${board.graveyard.length})</h3>
          ${cardGrid(board.graveyard, { empty: 'leer', imageCache, hoverDetailEnabled })}
        </div>
        <div class="zone exile-zone">
          <h3>Exil (${board.exile.length})</h3>
          ${cardGrid(board.exile, { empty: 'leer', imageCache, hoverDetailEnabled })}
        </div>
        <div class="zone library-zone">
          <h3>Bibliothek</h3>
          <p class="library-count">${board.library.length} Karten</p>
        </div>
        ${lifeBox('Du', board.life)}
      </section>

      <section class="zone-row player-hand-row">
        <div class="zone hand-zone">
          <h3>Hand (${board.hand.length})</h3>
          ${cardGrid(board.hand, { empty: 'leer', actionable: true, imageCache, hoverDetailEnabled })}
        </div>
      </section>

      <section class="board-controls">
        <button id="draw-btn" type="button">Karte ziehen</button>
        <button id="mulligan-btn" type="button">Mulligan (${board.mulligans})</button>
        <label class="detail-toggle">
          <input type="checkbox" id="hover-detail-checkbox" ${hoverDetailEnabled ? 'checked' : ''} />
          Kartendetails bei Hover
        </label>
      </section>
    </div>
  `;

  root.querySelector('#draw-btn').addEventListener('click', () => {
    setState({ board: drawCard(getState().board) });
  });

  root.querySelector('#mulligan-btn').addEventListener('click', () => {
    setState({ board: mulligan(getState().board, getState().deck) });
  });

  root.querySelector('#hover-detail-checkbox').addEventListener('change', (event) => {
    onToggleHoverDetail(event.target.checked);
  });

  root.querySelectorAll('.hand-zone .card[data-card-id]').forEach((el) => {
    el.addEventListener('click', () => {
      const cardId = el.dataset.cardId;
      setState({ board: moveToBattlefield(getState().board, cardId) });
    });
  });
}

function zonePlaceholder(label, isBattlefield = false) {
  return `
    <div class="zone opponent-zone ${isBattlefield ? 'battlefield-zone' : ''}">
      <h3>${label}</h3>
      <p class="empty-state">– (kein Gegner-Deck geladen)</p>
    </div>
  `;
}

function lifeBox(label, life) {
  return `
    <div class="zone life-zone">
      <h3>${label}</h3>
      <p class="life-total">${life}</p>
    </div>
  `;
}

function cardGrid(cards, { empty, actionable = false, imageCache, hoverDetailEnabled } = {}) {
  if (!cards.length) return `<p class="empty-state">${empty}</p>`;
  return `
    <div class="card-grid">
      ${cards.map((c) => renderCard(c, { actionable, imageCache, hoverDetailEnabled })).join('')}
    </div>
  `;
}

function renderCard(card, { actionable, imageCache, hoverDetailEnabled }) {
  // Name/type/mana cost/oracle text come from the data-hover-card tooltip
  // (cardHoverDetail.js) when enabled, instead of the native title
  // tooltip — title is kept only for the click-to-play hint, which that
  // panel doesn't show, and as a fallback name label when hover-detail is
  // switched off.
  const titleParts = [];
  if (!hoverDetailEnabled) titleParts.push(card.name);
  if (actionable) titleParts.push('Vorschau: klicken zum Spielen, ohne Regelprüfung');
  const title = titleParts.join(' — ');

  const image = imageCache?.get(card.name.toLowerCase());

  const inner = image?.small
    ? `<img src="${image.small}" alt="${escapeHtml(card.name)}" loading="lazy" />`
    : escapeHtml(card.name);

  const classes = ['card'];
  if (actionable) classes.push('clickable');
  if (image?.small) classes.push('has-image');

  const hoverAttr = hoverDetailEnabled ? ` data-hover-card="${escapeHtml(card.name)}"` : '';

  return `
    <div class="${classes.join(' ')}" data-card-id="${card.id}"${hoverAttr} title="${title}">
      ${inner}
    </div>`;
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}
