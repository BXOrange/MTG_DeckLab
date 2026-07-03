import { getState, setState, subscribe } from './state.js';
import { mulligan, drawCard, moveToBattlefield } from './boardEngine.js';

export function renderBoardView(container) {
  container.innerHTML = `<div id="board-root"></div>`;
  const root = container.querySelector('#board-root');
  renderBoard(root);
  subscribe(() => renderBoard(root));
}

function renderBoard(root) {
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
          ${cardGrid(board.battlefield, { empty: 'Keine Permanents', imageCache })}
        </div>
      </section>

      <section class="zone-row player-meta-row">
        <div class="zone command-zone">
          <h3>Command Zone</h3>
          ${cardGrid(board.commandZone, { empty: '–', imageCache })}
        </div>
        <div class="zone graveyard-zone">
          <h3>Friedhof (${board.graveyard.length})</h3>
          ${cardGrid(board.graveyard, { empty: 'leer', imageCache })}
        </div>
        <div class="zone exile-zone">
          <h3>Exil (${board.exile.length})</h3>
          ${cardGrid(board.exile, { empty: 'leer', imageCache })}
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
          ${cardGrid(board.hand, { empty: 'leer', actionable: true, imageCache })}
        </div>
      </section>

      <section class="board-controls">
        <button id="draw-btn" type="button">Karte ziehen</button>
        <button id="mulligan-btn" type="button">Mulligan (${board.mulligans})</button>
      </section>
    </div>
  `;

  root.querySelector('#draw-btn').addEventListener('click', () => {
    setState({ board: drawCard(getState().board) });
  });

  root.querySelector('#mulligan-btn').addEventListener('click', () => {
    setState({ board: mulligan(getState().board, getState().deck) });
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

function cardGrid(cards, { empty, actionable = false, imageCache } = {}) {
  if (!cards.length) return `<p class="empty-state">${empty}</p>`;
  return `
    <div class="card-grid">
      ${cards.map((c) => renderCard(c, { actionable, imageCache })).join('')}
    </div>
  `;
}

function renderCard(card, { actionable, imageCache }) {
  const title = escapeHtml(card.name) + (actionable ? ' (Vorschau: klicken zum Spielen, ohne Regelprüfung)' : '');
  const image = imageCache?.get(card.name.toLowerCase());

  const inner = image?.small
    ? `<img src="${image.small}" alt="${escapeHtml(card.name)}" loading="lazy" />`
    : escapeHtml(card.name);

  const classes = ['card'];
  if (actionable) classes.push('clickable');
  if (image?.small) classes.push('has-image');

  return `
    <div class="${classes.join(' ')}" data-card-id="${card.id}" title="${title}">
      ${inner}
    </div>`;
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}
