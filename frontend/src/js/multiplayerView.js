// "Multiplayer" — two tabs driven by one controller.
//
//   Setup  the lobby: who's connected (online / verfügbar / im Spiel),
//          which tables are forming, and — once you're at one — the seat
//          panel where each player picks a deck and accepts. When everyone
//          has accepted, the host starts the game.
//   Board  the shared game itself, disabled until there is one. It's the
//          same `gameBoardView.js` the Goldfisch and Replay tabs use, given
//          a multiplayer transport (every action is attributed to this seat)
//          and repainted from the pushes the lobby socket delivers.
//
// Backend: mtg_analyzer/api/multiplayer.py (REST) + api/multiplayer_ws.py
// (/ws/lobby). The socket is the source of truth for both screens — REST
// calls change things, the push says what changed — and it doubles as the
// presence signal, so it is opened on first visit and never closed.
//
// Hidden information is *not* this module's job: the server sends each seat
// its own redacted view (RULE 400.2, services/game_session.py), so an
// opponent's hand simply isn't in the data to leak.

import {
  concedeMultiplayerGame,
  createMultiplayerGame,
  fetchMultiplayerGame,
  joinMultiplayerGame,
  leaveMultiplayerGame,
  listSavedDecks,
  observeMultiplayerGame,
  sendMultiplayerAction,
  setMultiplayerDeck,
  setMultiplayerOptions,
  setMultiplayerReady,
  startMultiplayerGame,
  listTokenImages,
  tokenImageUrl,
  sleeveImageUrl,
} from './api.js';
import { connectLobbySocket } from './lobbySocket.js';
import { getPlayerName } from './settings.js';
import { createGameBoardView } from './gameBoardView.js';
import { analysisHtml } from './gameStats.js';
import { getState, setState } from './state.js';
import { preloadCardImages } from './cardImages.js';
import { parseDeckSections } from './parser.js';

const PRESENCE_LABELS = {
  online: { icon: '🟡', text: 'Online' },
  available: { icon: '🟢', text: 'Verfügbar' },
  playing: { icon: '🔵', text: 'Im Spiel' },
};

//: Why the server dropped this client, in words. The socket carries the
//: reason so the UI can say what happened instead of just flickering.
const DROP_REASONS = {
  idle: 'Wegen Inaktivität getrennt – dein Platz bleibt noch kurz reserviert.',
  replaced: 'In einem anderen Tab/Fenster mit demselben Namen übernommen.',
  timeout: 'Zeit abgelaufen – der Platz wurde freigegeben.',
  closed: 'Verbindung verloren – versuche erneut …',
};

const MULLIGAN_LABELS = {
  london: 'London-Mulligan (neue 7, dann N Karten unterlegen)',
  none: 'Kein Mulligan (Starthand wird behalten)',
};

/**
 * @param {{onBoardAvailable?: (available: boolean) => void, onEnterBoard?: () => void}} [hooks]
 *   `onBoardAvailable` toggles the Board tab's enabled state (it starts
 *   disabled — there is nothing to show without a game); `onEnterBoard`
 *   switches to it when a game actually starts.
 */
export function createMultiplayerView(hooks = {}) {
  let setupRoot = null;
  let boardRoot = null;

  let socket = null;
  let connected = false;
  let playerId = null;
  let lobby = { players: [], games: [] };
  /** The table this client is at (a seat or as an observer), or null. */
  let game = null;
  /** The latest session view for this seat — already redacted server-side. */
  let view = null;
  let savedDecks = null;
  let status = '';
  let statusKind = '';
  let busy = false;
  let newGameName = '';
  //: Notes about *this* client's connection and about the other players',
  //: shown as banners. Kept apart because they mean different things: one
  //: is "you dropped", the other "someone else did, keep playing".
  let connectionNote = '';
  let peerNote = '';

  // Cards picked to bottom when keeping a mulliganed hand (London), and the
  // end-of-match digest kept after the table closes so the review survives.
  let mulliganBottom = new Set();
  let summary = null;
  let assetsLoadedFor = null;
  //: The session id we've already switched the user to the Board tab for,
  //: so the switch happens once per game rather than on every push.
  let enteredBoardFor = null;

  const board = createGameBoardView({
    transport: {
      // Actions carry the seat, and the *pushed* view repaints the board:
      // returning no `data` tells gameBoardView to wait for it, so both
      // players' screens update from the same message rather than one of
      // them painting an HTTP reply that the other never saw.
      sendAction: async (action) => {
        if (!game || !playerId) return { ok: false, status: 0, data: null };
        const res = await sendMultiplayerAction(game.id, playerId, action);
        return { ok: res.ok, status: res.status, data: null, detail: res.data };
      },
    },
    // Undo and step-skipping are solo-practice affordances: one player can't
    // rewind a shared game, and fast-forwarding would skip the opponent's
    // response windows along with the empty steps.
    allowRewind: false,
    allowFastForward: false,
    onViewChange: (v) => {
      if (v) view = v;
    },
    extraControls: () => (isObserver() ? observerControls() : seatControls()),
    // Connection state is lobby data, not game state — hand it through so a
    // dropped opponent shows as absent on the board instead of just going
    // quiet (the server is passing priority for them).
    seatStatus: (id) => {
      const player = (lobby.players || []).find((pl) => pl.id === id);
      return player ? { connected: player.connected !== false } : null;
    },
  });

  function seatControls() {
    return [
      {
        id: 'concede',
        label: '🏳️ Aufgeben',
        title: 'Das Spiel aufgeben (Regel 104.3a) – normalerweise nur zu Hexerei-Zeitpunkten',
        disabled: busy || !!view?.state?.game_over,
        onClick: concede,
      },
    ];
  }

  function observerControls() {
    return [{ id: 'stop-watching', label: 'Zuschauen beenden', onClick: leaveGame }];
  }

  // --- Mounting -----------------------------------------------------------

  function mountSetup(el) {
    setupRoot = el;
    renderSetup();
  }

  function mountBoard(el) {
    boardRoot = el;
    board.mount(el);
    renderBoard();
  }

  /** The Multiplayer tab became visible. `which` is 'setup' or 'board'. */
  function onShown(which) {
    ensureSocket();
    // Presence: sitting in the lobby is "verfügbar"; the Board tab is still
    // the lobby as far as presence goes (the server derives "im Spiel" from
    // actually holding a seat, so this can't overwrite it).
    socket?.setPresence('available');
    if (savedDecks === null) loadDecks();
    // At a running table with nothing to draw — the pushes for it went to a
    // connection we no longer have (a reload), or the socket dropped and
    // reconnected. Pull the current position once instead of sitting on an
    // empty board waiting for the next move to happen.
    if (which === 'board' && game?.session_id && !view) refreshGameView();
    if (which === 'board') renderBoard();
    else renderSetup();
  }

  async function refreshGameView() {
    if (!game || !playerId) return;
    const res = await fetchMultiplayerGame(game.id, playerId);
    if (!res.ok || !res.data?.view) return;
    game = res.data.game;
    applyGameView(res.data.view);
    renderBoard();
  }

  /** The user navigated away from the Multiplayer tabs entirely. */
  function onHidden() {
    socket?.setPresence('online');
  }

  function ensureSocket() {
    if (socket) return;
    socket = connectLobbySocket({
      name: getPlayerName() || 'Spieler',
      onWelcome: (id, snapshot, reclaimed) => {
        playerId = id;
        lobby = snapshot;
        if (reclaimed) connectionNote = 'Platz zurückerhalten – das Spiel geht weiter.';
        syncMyGame();
        renderSetup();
        renderBoard();
      },
      onLobby: (snapshot) => {
        lobby = snapshot;
        syncMyGame();
        renderSetup();
        renderBoard();
      },
      onGame: (message) => {
        if (!message.game || (game && message.game.id !== game.id)) return;
        game = message.game;
        if (message.view) applyGameView(message.view);
        renderSetup();
        renderBoard();
      },
      onStatus: (isConnected, droppedReason) => {
        connected = isConnected;
        if (!isConnected) {
          connectionNote = DROP_REASONS[droppedReason] || 'Verbindung verloren – versuche erneut …';
        } else if (droppedReason) {
          connectionNote = `Wieder verbunden (${DROP_REASONS[droppedReason] || droppedReason}).`;
        } else {
          connectionNote = '';
        }
        renderSetup();
        renderBoard();
      },
      onPeerPresence: (peerId, isOnline, message) => {
        // Somebody else's socket came or went. Their seat is held for a
        // grace period, so this is information, not a game event — the
        // board keeps playing (the server passes priority for them).
        if (peerId === playerId) return;
        peerNote = isOnline
          ? `${message.name || 'Ein Spieler'} ist wieder da.`
          : `${message.name || 'Ein Spieler'} hat die Verbindung verloren – der Platz bleibt kurz reserviert.`;
        renderSetup();
        renderBoard();
      },
    });
  }

  /** Re-derive "which table am I at?" from a fresh lobby snapshot. */
  function syncMyGame() {
    if (!playerId) return;
    const mine = (lobby.games || []).find(
      (g) =>
        g.seats.some((s) => s.player_id === playerId) || (g.observer_ids || []).includes(playerId),
    );
    game = mine || null;
    if (!game) {
      view = null;
      enteredBoardFor = null;
    }
    hooks.onBoardAvailable?.(!!game);
  }

  function applyGameView(fresh) {
    view = fresh;
    if (fresh.setup && !fresh.setup.complete) {
      // Still in the mulligan phase — the shared board can't draw that, so
      // this module renders it itself (`renderMulligan`).
      mulliganBottom = new Set();
    } else {
      board.start(view.session_id, view);
    }
    // The first view for a table means the game just started: unblock the
    // Board tab and take everyone there, mulligan screen included (that's
    // the first thing each player has to do).
    if (enteredBoardFor !== fresh.session_id) {
      enteredBoardFor = fresh.session_id;
      hooks.onBoardAvailable?.(true);
      hooks.onEnterBoard?.();
    }
    if (fresh.state?.game_over && !summary) {
      summary = { analysis: fresh.analysis, state: fresh.state };
    }
    loadPlayerAssets();
  }

  async function loadDecks() {
    savedDecks = (await listSavedDecks()) || [];
    renderSetup();
  }

  // The local player's uploaded art (Einstellungen tab) + the sleeve chosen
  // for their deck — the sleeve doubles as the back of the *opponent's*
  // hidden hand cards here (gameBoardView's `faceDownCardHtml`).
  async function loadPlayerAssets() {
    const name = getPlayerName();
    if (!name || assetsLoadedFor === name) return;
    assetsLoadedFor = name;
    const images = await listTokenImages(name);
    const tokenImages = {};
    for (const t of images || []) {
      tokenImages[(t.token_name || '').toLowerCase()] = tokenImageUrl(name, t.token_name);
    }
    const deck = mySavedDeck();
    board.setAssets({
      tokenImages,
      sleeveImageUrl: deck?.sleeveId ? sleeveImageUrl(name, deck.sleeveId) : null,
    });
  }

  // --- Lobby actions ------------------------------------------------------

  async function withBusy(pendingText, fn) {
    busy = true;
    setStatus(pendingText, 'pending');
    renderSetup();
    renderBoard();
    try {
      await fn();
    } finally {
      busy = false;
      renderSetup();
      renderBoard();
    }
  }

  function setStatus(text, kind = '') {
    status = text;
    statusKind = kind;
  }

  /** Apply a lobby REST reply: report failures, adopt the new table state. */
  function applyLobbyResult(res, okText = '') {
    if (res.ok) {
      if (res.data?.lobby) lobby = res.data.lobby;
      if (res.data?.game !== undefined) game = res.data.game;
      if (res.data?.view) applyGameView(res.data.view);
      hooks.onBoardAvailable?.(!!game);
      setStatus(okText, okText ? 'ok' : '');
      return true;
    }
    if (res.status === 0) setStatus('Server nicht erreichbar.', 'warning');
    else setStatus(detailText(res) || `Fehler (${res.status}).`, 'warning');
    return false;
  }

  async function createGame() {
    if (!playerId) return;
    await withBusy('Spiel wird erstellt …', async () => {
      applyLobbyResult(await createMultiplayerGame(playerId, newGameName), 'Spiel erstellt.');
      newGameName = '';
    });
  }

  async function joinGame(gameId) {
    await withBusy('Beitreten …', async () => {
      applyLobbyResult(await joinMultiplayerGame(gameId, playerId));
    });
  }

  async function observeGame(gameId) {
    await withBusy('Zuschauen …', async () => {
      if (applyLobbyResult(await observeMultiplayerGame(gameId, playerId))) hooks.onEnterBoard?.();
    });
  }

  async function leaveGame() {
    if (!game) return;
    const gameId = game.id;
    await withBusy('Verlassen …', async () => {
      const res = await leaveMultiplayerGame(gameId, playerId);
      if (res.ok) {
        board.stop(); // no live board any more — stop its auto-pass countdown
        game = null;
        view = null;
        summary = null;
        enteredBoardFor = null;
        lobby = res.data?.lobby || lobby;
        hooks.onBoardAvailable?.(false);
        setStatus('Spiel verlassen.', '');
      } else {
        setStatus(detailText(res) || `Fehler (${res.status}).`, 'warning');
      }
    });
  }

  async function chooseDeck(deckId) {
    if (!game || !deckId) return;
    await withBusy('Deck wird gesetzt …', async () => {
      applyLobbyResult(await setMultiplayerDeck(game.id, playerId, deckId));
      await preloadOwnDeck();
    });
  }

  async function changeMulliganStyle(style) {
    if (!game) return;
    await withBusy('Einstellung wird gespeichert …', async () => {
      applyLobbyResult(await setMultiplayerOptions(game.id, playerId, { mulliganStyle: style }));
    });
  }

  async function toggleReady(ready) {
    if (!game) return;
    await withBusy(ready ? 'Bereit …' : 'Bereitschaft zurückgenommen …', async () => {
      applyLobbyResult(await setMultiplayerReady(game.id, playerId, ready));
    });
  }

  async function startGame() {
    if (!game) return;
    await withBusy('Spiel wird gestartet …', async () => {
      const res = await startMultiplayerGame(game.id, playerId);
      if (res.ok) {
        summary = null;
        applyLobbyResult(res, 'Spiel gestartet.');
      } else if (res.status === 422) {
        const detail = res.data?.detail || {};
        const errors = (detail.errors || []).join(' ');
        setStatus(`${detail.message || 'Start abgelehnt.'} ${errors}`.trim(), 'warning');
      } else {
        setStatus(detailText(res) || `Start fehlgeschlagen (${res.status}).`, 'warning');
      }
    });
  }

  async function concede() {
    if (!game || !window.confirm('Wirklich aufgeben? Das beendet deine Partie.')) return;
    await withBusy('Aufgeben …', async () => {
      const res = await concedeMultiplayerGame(game.id, playerId);
      if (res.ok) {
        game = res.data.game;
        applyGameView(res.data.view);
      } else {
        setStatus(detailText(res) || `Fehler (${res.status}).`, 'warning');
      }
    });
  }

  // Preload this seat's card art before the match, the same way the Goldfisch
  // tab does — the board should never pop images in mid-game.
  async function preloadOwnDeck() {
    const deck = mySavedDeck();
    if (!deck) return;
    const names = parseDeckSections(deck).allCards.map((c) => c.name);
    const resolved = await preloadCardImages(names);
    const merged = new Map(getState().imageCache);
    for (const [name, entry] of resolved) merged.set(name, entry);
    setState({ imageCache: merged });
  }

  // --- Setup screen -------------------------------------------------------

  function renderSetup() {
    if (!setupRoot) return;
    setupRoot.innerHTML = `
      <div class="mp-setup">
        <h3>Multiplayer – Lobby</h3>
        ${connectionLineHtml()}
        ${noteHtml()}
        ${statusHtml()}
        ${game ? myGameHtml() : ''}
        <div class="mp-columns">
          <section class="mp-panel">
            <h4>Spiele</h4>
            ${gameListHtml()}
            ${game ? '' : newGameHtml()}
          </section>
          <section class="mp-panel">
            <h4>Spieler (${(lobby.players || []).length})</h4>
            ${playerListHtml()}
          </section>
        </div>
      </div>`;
    wireSetup();
  }

  // The two presence banners (see `connectionNote`/`peerNote`).
  function noteHtml() {
    return [
      connectionNote ? `<p class="server-status warning">${escapeHtml(connectionNote)}</p>` : '',
      peerNote ? `<p class="server-status pending">${escapeHtml(peerNote)}</p>` : '',
    ].join('');
  }

  function connectionLineHtml() {
    const name = escapeHtml(getPlayerName() || 'Spieler');
    return connected
      ? `<p class="server-status ok">Verbunden als <strong>${name}</strong>.</p>`
      : `<p class="server-status pending">Verbinde mit dem Server … (Name: <strong>${name}</strong>, änderbar im Profil)</p>`;
  }

  function playerListHtml() {
    const players = lobby.players || [];
    if (!players.length) return '<p class="empty-state">Niemand verbunden.</p>';
    return `<ul class="mp-player-list">${players
      .map((p) => {
        const label = PRESENCE_LABELS[p.state] || PRESENCE_LABELS.online;
        const me = p.id === playerId ? ' <span class="mp-you">(du)</span>' : '';
        return `<li class="mp-player mp-state-${escapeAttr(p.state)}">
          <span class="mp-dot" title="${escapeAttr(label.text)}">${label.icon}</span>
          <span class="mp-player-name">${escapeHtml(p.name)}${me}</span>
          <span class="mp-player-state">${escapeHtml(label.text)}</span>
        </li>`;
      })
      .join('')}</ul>`;
  }

  function gameListHtml() {
    const games = lobby.games || [];
    if (!games.length) return '<p class="empty-state">Keine Spiele. Erstelle eines!</p>';
    return `<ul class="mp-game-list">${games.map((g) => gameRowHtml(g)).join('')}</ul>`;
  }

  function gameRowHtml(g) {
    const mine = game && g.id === game.id;
    const statusText = {
      setup: 'in Vorbereitung',
      running: 'läuft',
      finished: 'beendet',
    }[g.status] || g.status;
    const seats = g.seats.map((s) => escapeHtml(s.name)).join(', ') || '—';
    const canJoin = !game && g.status === 'setup' && g.seats.length < g.num_players;
    const canWatch = !game && g.status !== 'setup';
    return `<li class="mp-game${mine ? ' mp-game-mine' : ''}">
      <div class="mp-game-head">
        <strong>${escapeHtml(g.name)}</strong>
        <span class="mp-game-status mp-status-${escapeAttr(g.status)}">${escapeHtml(statusText)}</span>
      </div>
      <div class="mp-game-seats">${g.seats.length}/${g.num_players} Plätze · ${seats}</div>
      <div class="mp-game-actions">
        ${canJoin ? `<button type="button" class="primary" data-join="${escapeAttr(g.id)}" ${busy ? 'disabled' : ''}>Beitreten</button>` : ''}
        ${canWatch ? `<button type="button" data-observe="${escapeAttr(g.id)}" ${busy ? 'disabled' : ''}>👁️ Zuschauen</button>` : ''}
      </div>
    </li>`;
  }

  function newGameHtml() {
    return `
      <div class="mp-new-game">
        <label for="mp-new-name">Neues Spiel</label>
        <input id="mp-new-name" type="text" placeholder="Name des Spiels (optional)" value="${escapeAttr(newGameName)}" />
        <button id="mp-create" type="button" class="primary" ${busy || !playerId ? 'disabled' : ''}>Spiel erstellen</button>
        <p class="hint">Aktuell werden zwei Spieler unterstützt.</p>
      </div>`;
  }

  /** The seat panel for the table this client is at. */
  function myGameHtml() {
    if (isObserver()) {
      return `
        <section class="mp-panel mp-my-game">
          <h4>👁️ Du schaust „${escapeHtml(game.name)}" zu</h4>
          <p class="hint">Im Board-Tab siehst du das öffentliche Spielfeld – ohne Handkarten.</p>
          <div class="gf-controls">
            <button id="mp-leave" type="button" ${busy ? 'disabled' : ''}>Zuschauen beenden</button>
          </div>
        </section>`;
    }
    const isHost = game.host_id === playerId;
    const mySeat = game.seats.find((s) => s.player_id === playerId);
    const running = game.status !== 'setup';
    return `
      <section class="mp-panel mp-my-game">
        <h4>${escapeHtml(game.name)} ${running ? '<span class="mp-game-status mp-status-running">läuft</span>' : ''}</h4>
        <ol class="mp-seat-list">
          ${game.seats.map((s, i) => seatRowHtml(s, i)).join('')}
        </ol>
        ${running ? '' : `
          <div class="mp-option-row">
            <label for="mp-mulligan">Mulligan-Regel</label>
            <select id="mp-mulligan" ${isHost && !busy ? '' : 'disabled'}>
              ${Object.entries(MULLIGAN_LABELS)
                .map(
                  ([value, label]) =>
                    `<option value="${value}"${game.mulligan_style === value ? ' selected' : ''}>${escapeHtml(label)}</option>`,
                )
                .join('')}
            </select>
            ${isHost ? '' : '<span class="hint">Nur der Host kann das ändern.</span>'}
          </div>
          <div class="mp-option-row">
            <label for="mp-deck">Dein Deck</label>
            <select id="mp-deck" ${busy ? 'disabled' : ''}>
              ${deckOptionsHtml(mySeat?.deck_id)}
            </select>
          </div>
        `}
        <div class="gf-controls">
          ${running ? '' : `
            <button id="mp-ready" type="button" class="${mySeat?.ready ? '' : 'primary'}" ${busy || !mySeat?.deck_id ? 'disabled' : ''}>
              ${mySeat?.ready ? '↩ Zusage zurücknehmen' : '✔ Bereit'}
            </button>
            <button id="mp-start" type="button" class="primary" ${busy || !game.all_ready || !isHost ? 'disabled' : ''}>
              ▶ Spiel starten
            </button>`}
          ${running ? `<button id="mp-goto-board" type="button" class="primary">Zum Spielfeld →</button>` : ''}
          <button id="mp-leave" type="button" ${busy ? 'disabled' : ''}>Verlassen</button>
        </div>
        ${running || game.all_ready ? '' : '<p class="hint">Das Spiel startet, sobald alle Plätze belegt sind und alle zugesagt haben.</p>'}
      </section>`;
  }

  function seatRowHtml(seat, index) {
    const me = seat.player_id === playerId;
    const host = seat.player_id === game.host_id;
    const conceded = (game.conceded_ids || []).includes(seat.player_id);
    return `<li class="mp-seat${me ? ' mp-seat-me' : ''}">
      <span class="mp-seat-index">${index + 1}.</span>
      <span class="mp-seat-name">${escapeHtml(seat.name)}${host ? ' 👑' : ''}${me ? ' <span class="mp-you">(du)</span>' : ''}</span>
      <span class="mp-seat-deck">${seat.deck_name ? escapeHtml(seat.deck_name) : '<em>kein Deck</em>'}</span>
      <span class="mp-seat-ready">${conceded ? '🏳️ aufgegeben' : seat.ready ? '✔ bereit' : '…'}</span>
    </li>`;
  }

  function deckOptionsHtml(selectedId) {
    if (savedDecks === null) return '<option>Lädt …</option>';
    if (!savedDecks.length) return '<option value="">— keine gespeicherten Decks —</option>';
    return [
      '<option value="">— Deck wählen —</option>',
      ...savedDecks.map(
        (d) =>
          `<option value="${escapeAttr(d.id)}"${d.id === selectedId ? ' selected' : ''}>${escapeHtml(d.name || 'Unbenanntes Deck')}</option>`,
      ),
    ].join('');
  }

  function wireSetup() {
    setupRoot.querySelector('#mp-create')?.addEventListener('click', createGame);
    setupRoot.querySelector('#mp-new-name')?.addEventListener('input', (e) => {
      newGameName = e.target.value; // no re-render: don't steal focus mid-typing
    });
    setupRoot.querySelectorAll('[data-join]').forEach((el) => {
      el.addEventListener('click', () => joinGame(el.dataset.join));
    });
    setupRoot.querySelectorAll('[data-observe]').forEach((el) => {
      el.addEventListener('click', () => observeGame(el.dataset.observe));
    });
    setupRoot.querySelector('#mp-leave')?.addEventListener('click', leaveGame);
    setupRoot.querySelector('#mp-deck')?.addEventListener('change', (e) => chooseDeck(e.target.value));
    setupRoot
      .querySelector('#mp-mulligan')
      ?.addEventListener('change', (e) => changeMulliganStyle(e.target.value));
    setupRoot.querySelector('#mp-ready')?.addEventListener('click', () => {
      const mySeat = game?.seats.find((s) => s.player_id === playerId);
      toggleReady(!mySeat?.ready);
    });
    setupRoot.querySelector('#mp-start')?.addEventListener('click', startGame);
    setupRoot.querySelector('#mp-goto-board')?.addEventListener('click', () => hooks.onEnterBoard?.());
  }

  // --- Board screen -------------------------------------------------------

  function renderBoard() {
    if (!boardRoot) return;
    if (!game) {
      boardRoot.innerHTML = `
        <div class="mp-board-empty">
          <h3>Kein aktives Spiel</h3>
          <p class="hint">Erstelle oder betritt im Tab <strong>Setup</strong> ein Spiel – danach wird hier das Spielfeld angezeigt.</p>
        </div>`;
      return;
    }
    if (summary && view?.state?.game_over) {
      renderSummary();
      return;
    }
    if (!view) {
      boardRoot.innerHTML = `
        <div class="mp-board-empty">
          <h3>${escapeHtml(game.name)}</h3>
          <p class="hint">Das Spiel wurde noch nicht gestartet. Sobald alle zugesagt haben, geht es hier los.</p>
        </div>`;
      return;
    }
    if (view.setup && !view.setup.complete && !isObserver()) {
      renderMulligan();
      return;
    }
    // Playing (or observing): the shared board repaints itself.
    if (view.setup && !view.setup.complete && isObserver()) {
      boardRoot.innerHTML = `
        <div class="mp-board-empty">
          <h3>${escapeHtml(game.name)}</h3>
          <p class="hint">Die Spieler wählen gerade ihre Starthände (Mulligan).</p>
        </div>`;
    }
  }

  // The multiplayer mulligan screen. Unlike Goldfisch's, each seat runs its
  // own copy in parallel — after keeping, this shows who the table is still
  // waiting for (`setup.waiting_for`).
  function renderMulligan() {
    const setup = view.setup;
    const me = view.state.players.find((p) => p.id === playerId);
    const bottomCount = setup.mulligan_count;
    const iAmDone = !setup.waiting_for.includes(playerId);
    const canKeep = mulliganBottom.size === bottomCount;
    const noMulligans = view.legal_actions.every((a) => a.type !== 'mulligan');

    if (iAmDone) {
      const waiting = setup.waiting_for
        .map((id) => view.state.players.find((p) => p.id === id)?.name || id)
        .map(escapeHtml)
        .join(', ');
      boardRoot.innerHTML = `
        <div class="goldfish-mulligan">
          <h3>Starthand behalten</h3>
          <p class="server-status pending">⏳ Warte auf: ${waiting} …</p>
        </div>`;
      return;
    }

    boardRoot.innerHTML = `
      <div class="goldfish-mulligan">
        <h3>Starthand</h3>
        <p class="hint">
          ${
            bottomCount === 0
              ? `Deine Starthand: ${me.hand.length} Karten.${noMulligans ? ' In diesem Spiel wird ohne Mulligan gespielt.' : ' Behalten, oder neu mischen (Mulligan)?'}`
              : `Mulligan Nr. ${bottomCount}: neue 7 Karten gezogen. Beim Behalten ${bottomCount === 1 ? 'muss 1 Karte' : `müssen ${bottomCount} Karten`} unten in die Bibliothek gelegt werden.`
          }
        </p>
        ${statusHtml()}
        <div class="card-grid gf-mulligan-hand">
          ${me.hand.map((o) => mulliganCardHtml(o, bottomCount)).join('')}
        </div>
        <div class="gf-controls">
          ${noMulligans ? '' : `<button id="mp-mulligan" type="button" ${busy ? 'disabled' : ''}>🔀 Mulligan (neue 7 ziehen)</button>`}
          <button id="mp-keep" type="button" class="primary" ${busy || !canKeep ? 'disabled' : ''}>
            ${bottomCount === 0 ? 'Hand behalten' : `Behalten (${mulliganBottom.size}/${bottomCount} unten ausgewählt)`}
          </button>
          <button id="mp-concede" type="button" ${busy ? 'disabled' : ''}>🏳️ Aufgeben</button>
        </div>
      </div>`;

    boardRoot.querySelector('#mp-mulligan')?.addEventListener('click', () => act({ type: 'mulligan' }));
    boardRoot.querySelector('#mp-keep')?.addEventListener('click', () =>
      act({ type: 'keep_hand', bottom_instance_ids: Array.from(mulliganBottom) }),
    );
    boardRoot.querySelector('#mp-concede')?.addEventListener('click', concede);
    boardRoot.querySelectorAll('[data-bottom-toggle]').forEach((el) => {
      el.addEventListener('click', () => toggleBottomCard(Number(el.dataset.bottomToggle)));
    });
  }

  function mulliganCardHtml(o, bottomCount) {
    const image = getState().imageCache?.get((o.name || '').toLowerCase());
    const inner = image?.small
      ? `<img src="${image.small}" alt="${escapeAttr(o.name)}" loading="lazy" />`
      : escapeHtml(o.name);
    const selected = mulliganBottom.has(o.instance_id);
    const classes = ['card'];
    if (image?.small) classes.push('has-image');
    if (bottomCount > 0) classes.push('clickable');
    if (selected) classes.push('selected-bottom');
    const toggle = bottomCount > 0 ? ` data-bottom-toggle="${o.instance_id}"` : '';
    return `
      <div class="gf-card-slot">
        <div class="${classes.join(' ')}" data-hover-card="${escapeAttr(o.name)}" title="${escapeAttr(o.name)}"${toggle}>${inner}</div>
        ${bottomCount > 0 ? `<button type="button" class="gf-card-action" data-bottom-toggle="${o.instance_id}">${selected ? '✓ unten' : 'Nach unten legen'}</button>` : ''}
      </div>`;
  }

  function toggleBottomCard(instanceId) {
    const bottomCount = view?.setup?.mulligan_count || 0;
    if (mulliganBottom.has(instanceId)) mulliganBottom.delete(instanceId);
    else if (mulliganBottom.size < bottomCount) mulliganBottom.add(instanceId);
    renderBoard();
  }

  /** Setup-phase actions; once playing, the shared board's own act() runs. */
  async function act(action) {
    if (!game || !playerId) return;
    await withBusy('…', async () => {
      const res = await sendMultiplayerAction(game.id, playerId, action);
      if (res.ok) {
        game = res.data.game;
        applyGameView(res.data.view);
        setStatus('', '');
      } else {
        setStatus(detailText(res) || `Fehler (${res.status}).`, 'warning');
      }
    });
  }

  function renderSummary() {
    const s = summary.state;
    const me = s.players.find((p) => p.id === playerId);
    const winner = s.winner_id ? s.players.find((p) => p.id === s.winner_id) : null;
    const won = winner && me && winner.id === me.id;
    const banner = winner
      ? won
        ? '🏆 Gewonnen!'
        : `Verloren – Sieger: ${escapeHtml(winner.name)}.`
      : 'Spiel beendet.';
    boardRoot.innerHTML = `
      <div class="goldfish-summary">
        <h3>Partie-Auswertung</h3>
        <p class="server-status ${won ? 'ok' : 'warning'}">${banner}</p>
        ${analysisHtml(summary.analysis)}
        <div class="gf-controls">
          <button id="mp-summary-leave" type="button" class="primary">Zurück in die Lobby</button>
        </div>
      </div>`;
    boardRoot.querySelector('#mp-summary-leave')?.addEventListener('click', async () => {
      summary = null;
      await leaveGame();
    });
  }

  // --- Small helpers ------------------------------------------------------

  function isObserver() {
    return !!game && !game.seats.some((s) => s.player_id === playerId);
  }

  function mySavedDeck() {
    const seat = game?.seats.find((s) => s.player_id === playerId);
    return seat?.deck_id ? (savedDecks || []).find((d) => d.id === seat.deck_id) : null;
  }

  function statusHtml() {
    if (!status) return '';
    return `<p class="server-status ${statusKind}">${escapeHtml(status)}</p>`;
  }

  function detailText(res) {
    const detail = res.data?.detail;
    if (!detail) return '';
    return typeof detail === 'string' ? detail : detail.message || '';
  }

  return { mountSetup, mountBoard, onShown, onHidden };
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str == null ? '' : String(str);
  return div.innerHTML;
}

function escapeAttr(str) {
  return escapeHtml(str).replace(/"/g, '&quot;');
}
