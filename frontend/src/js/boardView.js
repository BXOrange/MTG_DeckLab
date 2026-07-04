import { getState, setState, subscribe } from './state.js';
import { mulligan, drawCard, moveToBattlefield } from './boardEngine.js';
import { createGoldfishView } from './goldfishView.js';
import { startMultiplayer } from './api.js';

export function renderBoardView(container) {
  container.innerHTML = `<div id="board-root"></div>`;
  const root = container.querySelector('#board-root');

  // The play area has three modes (the deck's new emphasis, UC3/UC4):
  //   - goldfish: play the deck against the real backend rules engine
  //     (server-held session, with rewind/restart) — the default.
  //   - preview: the old local, rule-less board (drag a card anywhere).
  //   - multiplayer: a stub until interactive two-player priority exists.
  let mode = 'goldfish';
  // Local UI preference for the preview board only.
  let hoverDetailEnabled = true;
  // Persistent across mode switches so a running goldfish game survives
  // toggling to another mode and back (its session lives inside).
  const goldfish = createGoldfishView();

  function renderContent() {
    const content = root.querySelector('#board-mode-content');
    if (!content) return;
    if (mode === 'goldfish') goldfish.mount(content);
    else if (mode === 'multiplayer') renderMultiplayerStub(content);
    else renderLocalPreview(content);
  }

  function renderLocalPreview(content) {
    renderBoard(content, {
      hoverDetailEnabled,
      onToggleHoverDetail: (checked) => {
        hoverDetailEnabled = checked;
        if (mode === 'preview') renderLocalPreview(content);
      },
    });
  }

  function renderShell() {
    const tab = (id, label) =>
      `<button class="mode-btn ${mode === id ? 'active' : ''}" data-mode="${id}" type="button">${label}</button>`;
    root.innerHTML = `
      <div class="board-mode-bar">
        ${tab('goldfish', 'Goldfisch')}
        ${tab('preview', 'Lokale Vorschau')}
        ${tab('multiplayer', 'Multiplayer')}
      </div>
      <div id="board-mode-content"></div>
    `;
    root.querySelectorAll('.mode-btn').forEach((btn) => {
      btn.addEventListener('click', () => {
        mode = btn.dataset.mode;
        renderShell();
      });
    });
    renderContent();
  }

  renderShell();
  // The preview board mirrors global deck/board state; the goldfish board
  // is server-driven and manages its own DOM, so only re-render on state
  // changes while the preview is showing.
  subscribe(() => {
    if (mode === 'preview') renderContent();
  });
}

function renderMultiplayerStub(content) {
  content.innerHTML = `
    <div class="mp-stub">
      <h3>Multiplayer-Modus</h3>
      <p class="hint">
        Zwei menschliche Spieler mit Prioritäts-System (RULE 117) – noch in
        Arbeit. Das Backend kennt den Modus bereits, die interaktive
        Prioritäts-Schleife fehlt aber noch.
      </p>
      <button id="mp-try" type="button">Multiplayer testen</button>
      <p class="server-status" id="mp-status"></p>
    </div>
  `;
  content.querySelector('#mp-try').addEventListener('click', async () => {
    const st = content.querySelector('#mp-status');
    st.textContent = 'Frage Server …';
    st.className = 'server-status pending';
    const res = await startMultiplayer();
    if (res.status === 501) {
      st.textContent = res.data?.detail || 'Multiplayer ist noch nicht verfügbar.';
      st.className = 'server-status warning';
    } else if (res.status === 0) {
      st.textContent = 'Server nicht erreichbar.';
      st.className = 'server-status warning';
    } else {
      st.textContent = `Unerwartete Antwort (${res.status}).`;
      st.className = 'server-status';
    }
  });
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
