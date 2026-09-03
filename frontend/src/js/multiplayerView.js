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
  addMultiplayerBot,
  concedeMultiplayerGame,
  createMultiplayerGame,
  exportReplay,
  fetchBotKinds,
  fetchGameFormats,
  fetchMultiplayerGame,
  joinMultiplayerGame,
  leaveMultiplayerGame,
  listFavoriteDecks,
  listSavedDecks,
  observeMultiplayerGame,
  removeMultiplayerBot,
  sendMultiplayerAction,
  setMultiplayerBannerColor,
  setMultiplayerDeck,
  setMultiplayerOptions,
  setMultiplayerReady,
  startMultiplayerGame,
  takeBackMultiplayerMove,
  listTokenImages,
  tokenImageUrl,
  sleeveImageUrl,
} from './api.js';
import { connectLobbySocket } from './lobbySocket.js';
import {
  getPlayerName,
  getClientToken,
  getMpDefaultFormat,
  getMpDefaultMulliganStyle,
  getMpDefaultSeats,
  getMpDefaultTakebacks,
  getMpDefaultRandomizeSeating,
  getMpDefaultRandomStartingPlayer,
} from './settings.js';
import { createGameBoardView } from './gameBoardView.js';
import { analysisHtml } from './gameStats.js';
import { getState, setState } from './state.js';
import { preloadCardImages } from './cardImages.js';
import { parseDeckSections } from './parser.js';
import { MULLIGAN_LABELS, SEAT_COUNTS, mulliganText } from './mulligan.js';
import {
  BANNER_COLORS,
  COLORLESS_BANNER,
  bannerColorLabel,
  bannerGradients,
  normalizeBannerColor,
} from './bannerColors.js';
import {
  escapeHtml,
  escapeAttr,
  deckSelectOptionsHtml,
  formatSelectOptionsHtml,
  mulliganTileHtml,
  resultBannerHtml,
  loadUnmodeledDeckIds,
} from './gameSetup.js';

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
  // VIS-1: distinct from "loaded, zero decks" — otherwise a network failure
  // silently rendered as "— keine gespeicherten Decks —" with no indication
  // anything went wrong.
  let decksLoadError = false;
  //: This player's starred deck ids (Profil tab) — deckOptionsHtml() lists
  //: them first, same convention as goldfishView.js's picker.
  let favoriteDeckIds = new Set();
  //: Saved-deck ids holding cards the engine doesn't model yet — drives the
  //: "⚠️" marker in the deck pickers (own seat + bot seats). Filled
  //: asynchronously after the deck list loads.
  let unmodeledDeckIds = new Set();
  //: The bot kinds the server offers (GET /api/multiplayer/bots), fetched
  //: once — they're a property of the backend, not of this table.
  let botKinds = null;
  let botKindToAdd = '';
  //: PLR-13: the RULE 8/9 format catalogue (GET /api/game/formats), fetched
  //: once like `botKinds` — a property of the backend, not of this table.
  let gameFormats = null;
  //: Which seat's banner-colour picker is currently unfolded (a seat's
  //: `player_id`, or null). Only one at a time, and never persisted — it's
  //: a disclosure toggle on a row, not a setting.
  let bannerPickerFor = null;
  let status = '';
  let statusKind = '';
  let busy = false;
  let newGameName = '';
  //: Seats the "Spiel erstellen" form asks for (2-4) — this player's saved
  //: default (Profil tab) until they change it for one particular table.
  let newGameSeats = getMpDefaultSeats();
  //: Notes about *this* client's connection and about the other players',
  //: shown as banners. Kept apart because they mean different things: one
  //: is "you dropped", the other "someone else did, keep playing".
  let connectionNote = '';
  let peerNote = '';

  // Cards picked to bottom when keeping a mulliganed hand (London), and the
  // end-of-match digest kept after the table closes so the review survives.
  let mulliganBottom = new Set();
  let summary = null;
  //: With the game over the player can flip between the final position and
  //: the digest, and closes the table when *they* decide to — a finished
  //: game is no longer urgent, and being thrown out of the board the
  //: instant somebody dies means never getting to look at why.
  let showSummary = true;
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
      const seat = game?.seats.find((s) => s.player_id === id);
      // Both facts are lobby-side, but they come from different places: a
      // bot has a seat and no `LobbyPlayer` in the list at all, so its
      // banner must still be found (and it is never "disconnected").
      if (!player && !seat) return null;
      return {
        connected: player ? player.connected !== false : true,
        banner_color: seat?.banner_color || null,
      };
    },
  });

  // PLR-10: the same "save the current position as a Replay file" affordance
  // goldfishView.js has, ported here — a shared game's board can be
  // downloaded and re-opened in the Replay tab exactly like a goldfish
  // position can (the export endpoint is already generic on session id). A
  // function, not a plain object, so `disabled` reflects the *current*
  // `busy` at each call — like every other control below, it's rebuilt on
  // every `seatControls()` call rather than captured once.
  function exportControl() {
    return {
      id: 'export',
      label: '⬇ Als Replay speichern',
      title: 'Diesen Spielzustand als Replay-Datei speichern (im Replay-Tab wieder ladbar)',
      disabled: busy,
      onClick: exportReplayFile,
    };
  }

  function seatControls() {
    // Once it's over there is nothing left to concede — the buttons become
    // "look at the digest" and "close this table for good".
    if (view?.state?.game_over) {
      return [
        {
          id: 'summary',
          label: '📊 Auswertung',
          title: 'Die Partie-Auswertung statt des Spielfelds anzeigen',
          onClick: () => {
            showSummary = true;
            renderBoard();
          },
        },
        exportControl(),
        {
          id: 'close',
          label: '✖ Spiel schließen',
          title: 'Die Partie beenden und den Tisch auflösen',
          disabled: busy,
          onClick: closeGame,
        },
      ];
    }
    const controls = [
      {
        id: 'concede',
        label: '🏳️ Aufgeben',
        title: 'Das Spiel aufgeben (Regel 104.3a) – normalerweise nur zu Hexerei-Zeitpunkten',
        disabled: busy,
        onClick: concede,
      },
      exportControl(),
    ];
    // Only shown at all when the host configured a budget (an empty
    // `takebacks_remaining` means the table has none) — otherwise there's
    // nothing this button could ever do.
    const remaining = view?.takebacks_remaining?.[playerId];
    if (remaining !== undefined) {
      controls.push({
        id: 'takeback',
        label: `↩️ Zug zurücknehmen (${remaining})`,
        title: 'Nimmt deinen eigenen letzten Zug zurück – geht dabei auch auf Züge zurück, die der Gegner seitdem gemacht hat, da es nur eine gemeinsame Zeitleiste gibt. Reduziert dein Kontingent um eins.',
        disabled: busy || remaining <= 0,
        onClick: takeBack,
      });
    }
    return controls;
  }

  // Same download-as-file pattern as goldfishView.js's `exportReplayFile`.
  async function exportReplayFile() {
    if (!game?.session_id) return;
    const res = await exportReplay(game.session_id);
    if (!res.ok || !res.data) {
      setStatus(`Export fehlgeschlagen (${res.status}).`, 'warning');
      renderBoard();
      return;
    }
    const blob = new Blob([JSON.stringify(res.data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'replay.json';
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    setStatus('Als Replay gespeichert.', 'ok');
    renderBoard();
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
    if (savedDecks === null || decksLoadError) loadDecks();
    if (botKinds === null) loadBotKinds();
    if (gameFormats === null) loadFormats();
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
      clientToken: getClientToken() || null,
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
      // VIS-6: warm every seat's art now, not just this client's own deck
      // (`preloadOwnDeck`, run earlier at deck-pick time) — otherwise an
      // opponent's first play pops in.
      preloadAllDecksArt();
    }
    if (fresh.state?.game_over && !summary) {
      summary = { analysis: fresh.analysis, state: fresh.state };
    }
    loadPlayerAssets();
  }

  async function loadDecks() {
    const name = getPlayerName();
    const [decks, favorites] = await Promise.all([
      listSavedDecks(),
      name ? listFavoriteDecks(name) : Promise.resolve([]),
    ]);
    decksLoadError = decks === null;
    savedDecks = decks || [];
    favoriteDeckIds = new Set(favorites || []);
    renderSetup();
    // Coverage marker — non-blocking, repaints once the checks land.
    loadUnmodeledDeckIds(savedDecks).then((ids) => {
      unmodeledDeckIds = ids;
      if (ids.size) renderSetup();
    });
  }

  async function loadBotKinds() {
    botKinds = []; // don't re-fetch while this one is in flight
    const res = await fetchBotKinds();
    botKinds = res.ok ? res.data?.bots || [] : [];
    if (!botKindToAdd && botKinds.length) botKindToAdd = botKinds[0].kind;
    renderSetup();
  }

  // PLR-13: the format catalogue for the table-options picker.
  async function loadFormats() {
    gameFormats = []; // don't re-fetch while this one is in flight
    const res = await fetchGameFormats();
    gameFormats = res.ok ? res.data?.formats || [] : [];
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
      const created = applyLobbyResult(
        await createMultiplayerGame(playerId, newGameName, newGameSeats),
        'Spiel erstellt.',
      );
      newGameName = '';
      // PLR-13 + Profil "Mehrspieler-Standardeinstellungen": apply this
      // host's saved table defaults right away, one host-only options call
      // — the same route the Setup screen's own option rows already use,
      // so nothing here needs to duplicate their validation.
      if (created && game) {
        await setMultiplayerOptions(game.id, playerId, {
          gameFormat: getMpDefaultFormat(),
          mulliganStyle: getMpDefaultMulliganStyle(),
          takebacksPerPlayer: getMpDefaultTakebacks(),
          randomizeSeating: getMpDefaultRandomizeSeating(),
          randomStartingPlayer: getMpDefaultRandomStartingPlayer(),
        }).then((res) => applyLobbyResult(res));
      }
    });
  }

  async function changeSeatCount(count) {
    if (!game) return;
    const n = Math.max(2, Math.min(4, Math.floor(Number(count)) || 2));
    await withBusy('Einstellung wird gespeichert …', async () => {
      applyLobbyResult(await setMultiplayerOptions(game.id, playerId, { numPlayers: n }));
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
        showSummary = true;
        enteredBoardFor = null;
        lobby = res.data?.lobby || lobby;
        hooks.onBoardAvailable?.(false);
        setStatus('Spiel verlassen.', '');
      } else {
        setStatus(detailText(res) || `Fehler (${res.status}).`, 'warning');
      }
    });
  }

  /** Pick a deck. `seatId` set = picking for a bot's seat as the host. */
  async function chooseDeck(deckId, seatId = null) {
    if (!game || !deckId) return;
    await withBusy('Deck wird gesetzt …', async () => {
      applyLobbyResult(await setMultiplayerDeck(game.id, playerId, deckId, seatId));
      if (!seatId) await preloadOwnDeck();
    });
  }

  /**
   * Repaint a seat's banner. `seatId` is the seat being painted — this
   * client's own, or a bot's if this client is the host; the server checks
   * that either way (`services/lobby.py`'s `_seat_to_configure`).
   *
   * Sent straight through on every click rather than staged locally: it
   * costs nothing, it can't be wrong (an unknown key normalizes, it never
   * clears anybody's acceptance), and it means the other players watch the
   * colour appear while you are still choosing it.
   */
  async function chooseBannerColor(color, seatId = null) {
    if (!game || !color) return;
    const forOwnSeat = !seatId || seatId === playerId;
    await withBusy('Banner-Farbe wird gesetzt …', async () => {
      applyLobbyResult(
        await setMultiplayerBannerColor(game.id, playerId, color, forOwnSeat ? null : seatId),
      );
    });
  }

  async function addBot(kind) {
    if (!game || !kind) return;
    await withBusy('Bot wird eingesetzt …', async () => {
      applyLobbyResult(await addMultiplayerBot(game.id, playerId, kind), 'Bot eingesetzt.');
    });
  }

  async function removeBot(botId) {
    if (!game || !botId) return;
    await withBusy('Bot wird entfernt …', async () => {
      applyLobbyResult(await removeMultiplayerBot(game.id, playerId, botId), 'Bot entfernt.');
    });
  }

  async function changeMulliganStyle(style) {
    if (!game) return;
    await withBusy('Einstellung wird gespeichert …', async () => {
      applyLobbyResult(await setMultiplayerOptions(game.id, playerId, { mulliganStyle: style }));
    });
  }

  // PLR-13: the table's format (Planechase/Archenemy/Vanguard/…). Clearing
  // to Commander also clears any Archenemy pick — it only means anything
  // once the format actually has that variant.
  async function changeGameFormat(name) {
    if (!game) return;
    await withBusy('Einstellung wird gespeichert …', async () => {
      applyLobbyResult(await setMultiplayerOptions(game.id, playerId, { gameFormat: name }));
    });
  }

  // RULE 904: which seat is the Archenemy. `''` clears back to the
  // server's own default (the host — `api/multiplayer.py`'s `start_game`).
  async function changeArchenemy(seatPlayerId) {
    if (!game) return;
    await withBusy('Einstellung wird gespeichert …', async () => {
      applyLobbyResult(await setMultiplayerOptions(game.id, playerId, { archenemyId: seatPlayerId }));
    });
  }

  // RULE 103.1/103.2 as two table settings — the server applies them once,
  // when the game is built (`LobbyGame.seating_order`), so nothing here has
  // to (or could) preview the result.
  async function changeRandomization(options) {
    if (!game) return;
    await withBusy('Einstellung wird gespeichert …', async () => {
      applyLobbyResult(await setMultiplayerOptions(game.id, playerId, options));
    });
  }

  async function changeTakebacksPerPlayer(count) {
    if (!game) return;
    const n = Math.max(0, Math.min(20, Math.floor(Number(count)) || 0));
    await withBusy('Einstellung wird gespeichert …', async () => {
      applyLobbyResult(await setMultiplayerOptions(game.id, playerId, { takebacksPerPlayer: n }));
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
        showSummary = true;
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

  /** End of the match: drop the table and go back to the lobby. */
  async function closeGame() {
    summary = null;
    showSummary = true;
    await leaveGame();
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

  async function takeBack() {
    if (!game) return;
    await withBusy('Zug wird zurückgenommen …', async () => {
      const res = await takeBackMultiplayerMove(game.id, playerId);
      if (res.ok) {
        game = res.data.game;
        applyGameView(res.data.view);
        setStatus('Zug zurückgenommen.', 'ok');
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

  // VIS-6: every seat's deck, not just this client's own — an opponent's
  // saved deck is readable the same way `mySavedDeck()` reads yours (this
  // app has no accounts, so `listSavedDecks()` is already unscoped), so
  // there's no reason their first play should pop in art nobody warmed.
  // Called once, when the table's first view arrives (deck picks are
  // locked in by then).
  async function preloadAllDecksArt() {
    if (!game) return;
    if (savedDecks === null) await loadDecks();
    const decks = (game.seats || [])
      .map((seat) => (savedDecks || []).find((d) => d.id === seat.deck_id))
      .filter(Boolean);
    const names = new Set();
    for (const deck of decks) {
      for (const card of parseDeckSections(deck).allCards) names.add(card.name);
    }
    if (!names.size) return;
    const resolved = await preloadCardImages(Array.from(names));
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
        <select id="mp-new-seats" title="Wie viele Plätze hat der Tisch?" ${busy ? 'disabled' : ''}>
          ${SEAT_COUNTS.map(
            (n) => `<option value="${n}"${n === newGameSeats ? ' selected' : ''}>${n} Spieler</option>`,
          ).join('')}
        </select>
        <button id="mp-create" type="button" class="primary" ${busy || !playerId ? 'disabled' : ''}>Spiel erstellen</button>
        <p class="hint">Zwei bis vier Spieler – die Plätze lassen sich bis zum Start noch ändern.</p>
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
        ${running ? '' : addBotHtml()}
        ${running ? '' : `
          <div class="mp-option-row" title="Zwei bis vier Plätze. Verkleinern geht nur bis zur Zahl der Spieler, die schon sitzen.">
            <label for="mp-seats">Plätze</label>
            <select id="mp-seats" ${isHost && !busy ? '' : 'disabled'}>
              ${SEAT_COUNTS.map(
                (n) =>
                  `<option value="${n}"${game.num_players === n ? ' selected' : ''}${
                    n < game.seats.length ? ' disabled' : ''
                  }>${n} Spieler</option>`,
              ).join('')}
            </select>
            ${isHost ? '' : '<span class="hint">Nur der Host kann das ändern.</span>'}
          </div>
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
          <div class="mp-option-row" title="Regel 8/9: Planechase, Archenemy und Vanguard bringen eine eigene Kartenzone mit (Planarkarten/Schema-Decks/Avatar). Wirkt sich erst auf das nächste gestartete Spiel aus.">
            <label for="mp-format">Format</label>
            <select id="mp-format" ${isHost && !busy ? '' : 'disabled'}>
              ${formatOptionsHtml(game.game_format)}
            </select>
            ${isHost ? '' : '<span class="hint">Nur der Host kann das ändern.</span>'}
          </div>
          ${archenemyRowHtml(isHost)}
          <div class="mp-option-row" title="Regel 103.1/103.2: Wer sitzt wo, und wer fängt an? Ohne Haken bleibt es bei der Reihenfolge, in der ihr euch gesetzt habt – der Host beginnt.">
            <label>Auslosen</label>
            <label class="mp-option-check">
              <input id="mp-random-seating" type="checkbox" ${game.randomize_seating ? 'checked' : ''} ${isHost && !busy ? '' : 'disabled'} />
              Sitzordnung (Regel 103.1)
            </label>
            <label class="mp-option-check">
              <input id="mp-random-start" type="checkbox" ${game.random_starting_player ? 'checked' : ''} ${isHost && !busy ? '' : 'disabled'} />
              Startspieler (Regel 103.2)
            </label>
            ${isHost ? '' : '<span class="hint">Nur der Host kann das ändern.</span>'}
          </div>
          <div class="mp-option-row" title="Erlaubt jedem Platz, seinen eigenen letzten Zug zurückzunehmen — begrenzt, damit es eine Ausnahme für Fehlklicks bleibt und keine allgemeine Undo-Funktion.">
            <label for="mp-takebacks">Take-backs je Spieler</label>
            <input id="mp-takebacks" type="number" min="0" max="20" value="${game.takebacks_per_player ?? 0}" ${isHost && !busy ? '' : 'disabled'} />
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
    // A bot has no client, so the host both picks its deck and takes it back
    // off the table — everything a human seat does for itself.
    const iAmHost = game.host_id === playerId;
    const canManage = seat.is_bot && iAmHost && game.status === 'setup';
    // You paint your own banner; the host paints the bots' (nobody else's,
    // and nobody's at all once the game is running — see `chooseBannerColor`).
    const canPaint = game.status === 'setup' && (me || canManage);
    const picking = canPaint && bannerPickerFor === seat.player_id;
    return `<li class="mp-seat${me ? ' mp-seat-me' : ''}${seat.is_bot ? ' mp-seat-bot' : ''}">
      <span class="mp-seat-index">${index + 1}.</span>
      ${bannerSwatchHtml(seat, canPaint, picking)}
      <span class="mp-seat-name">${seat.is_bot ? '🤖 ' : ''}${escapeHtml(seat.name)}${host ? ' 👑' : ''}${me ? ' <span class="mp-you">(du)</span>' : ''}</span>
      <span class="mp-seat-deck">${
        canManage
          ? `<select data-bot-deck="${escapeAttr(seat.player_id)}" ${busy ? 'disabled' : ''}>${deckOptionsHtml(seat.deck_id)}</select>`
          : seat.deck_name
            ? escapeHtml(seat.deck_name)
            : '<em>kein Deck</em>'
      }</span>
      <span class="mp-seat-ready">${conceded ? '🏳️ aufgegeben' : seat.ready ? '✔ bereit' : '…'}</span>
      ${
        canManage
          ? `<button type="button" class="mp-seat-remove" data-remove-bot="${escapeAttr(seat.player_id)}" title="Bot entfernen" ${busy ? 'disabled' : ''}>✕</button>`
          : ''
      }
      ${picking ? bannerPickerHtml(seat) : ''}
    </li>`;
  }

  /**
   * The seat's banner colour, as the board will paint it: a small chip of
   * the very same gradient (`bannerColors.js`), so what you pick here is
   * literally what you get there. Clickable — and a button rather than a
   * `<select>` — for whoever may repaint it, since 32 combinations is a
   * lousy dropdown but five toggles are an easy one (`bannerPickerHtml`).
   */
  function bannerSwatchHtml(seat, canPaint, picking) {
    const key = seat.banner_color;
    const style = key ? `background: ${bannerGradients(key).background}` : '';
    const label = key ? bannerColorLabel(key) : 'noch keine Farbe – wird aus dem Deck übernommen';
    const chip = `<span class="mp-banner-chip${key ? '' : ' mp-banner-chip-empty'}" style="${escapeAttr(style)}" aria-hidden="true"></span>`;
    if (!canPaint) {
      return `<span class="mp-seat-banner" title="Banner-Farbe: ${escapeAttr(label)}">${chip}</span>`;
    }
    return `<button type="button" class="mp-seat-banner mp-banner-edit" data-banner-toggle="${escapeAttr(seat.player_id)}"
      aria-expanded="${picking ? 'true' : 'false'}" title="Banner-Farbe wählen (aktuell: ${escapeAttr(label)})" ${busy ? 'disabled' : ''}>${chip}</button>`;
  }

  /**
   * The picker itself: one toggle per colour, in WUBRG order, plus the
   * deck's own identity as a one-click shortcut. Toggles rather than a list
   * of 32 named combinations, because a banner colour *is* a set — and
   * turning them all off is how you fly the grey colourless banner, which
   * is why there is no separate "grau" button.
   */
  function bannerPickerHtml(seat) {
    const current = normalizeBannerColor(seat.banner_color || COLORLESS_BANNER);
    const active = new Set(current === COLORLESS_BANNER ? [] : current.split(''));
    const deck = (savedDecks || []).find((d) => d.id === seat.deck_id);
    const fromDeck = deck?.colorIdentity ? normalizeBannerColor(deck.colorIdentity.join('')) : null;
    const toggles = BANNER_COLORS.map((c) => {
      const on = active.has(c.code);
      const next = on
        ? [...active].filter((code) => code !== c.code)
        : [...active, c.code];
      return `<button type="button" class="mp-banner-pip mp-banner-pip--${c.code}${on ? ' is-on' : ''}"
        data-banner-set="${escapeAttr(seat.player_id)}" data-banner-color="${escapeAttr(next.join('') || COLORLESS_BANNER)}"
        title="${escapeAttr(c.label)}" aria-pressed="${on ? 'true' : 'false'}" ${busy ? 'disabled' : ''}>${c.symbol}</button>`;
    }).join('');
    return `
      <div class="mp-banner-picker">
        <span class="mp-banner-pips">${toggles}</span>
        <span class="mp-banner-name">${escapeHtml(seat.banner_color ? bannerColorLabel(seat.banner_color) : 'Farblos (C)')}</span>
        ${
          fromDeck && fromDeck !== current
            ? `<button type="button" class="mp-banner-from-deck" data-banner-set="${escapeAttr(seat.player_id)}" data-banner-color="${escapeAttr(fromDeck)}" ${busy ? 'disabled' : ''}>🎨 Farbidentität des Decks (${escapeHtml(bannerColorLabel(fromDeck))})</button>`
            : ''
        }
        <span class="hint">Alle Farben aus = graues Banner (farblos).</span>
      </div>`;
  }

  /** Host-only row for seating a bot, while the table still has a free seat. */
  function addBotHtml() {
    if (game.host_id !== playerId || game.status !== 'setup') return '';
    if (game.seats.length >= game.num_players) return '';
    if (!botKinds || !botKinds.length) return '';
    const chosen = botKinds.find((b) => b.kind === botKindToAdd) || botKinds[0];
    return `
      <div class="mp-option-row mp-add-bot">
        <label for="mp-bot-kind">Bot einsetzen</label>
        <select id="mp-bot-kind" ${busy ? 'disabled' : ''}>
          ${botKinds
            .map(
              (b) =>
                `<option value="${escapeAttr(b.kind)}"${b.kind === chosen.kind ? ' selected' : ''}>${escapeHtml(b.label)}</option>`,
            )
            .join('')}
        </select>
        <button id="mp-add-bot" type="button" ${busy ? 'disabled' : ''}>🤖 Hinzufügen</button>
        <span class="hint">${escapeHtml(chosen.description || '')}</span>
      </div>`;
  }

  // Deck / format `<option>` lists — favorites-first sort + loading/error/
  // empty states shared with the Goldfisch and Solo pickers (`gameSetup.js`).
  function deckOptionsHtml(selectedId) {
    return deckSelectOptionsHtml({
      savedDecks,
      selectedId,
      favoriteDeckIds,
      unmodeledDeckIds,
      decksLoadError,
    });
  }

  // PLR-13: the format <select>'s options (GET /api/game/formats).
  function formatOptionsHtml(selectedName) {
    return formatSelectOptionsHtml(gameFormats, selectedName);
  }

  // RULE 904: only shown once the table's format actually has the
  // Archenemy variant — an empty seat picker for every other format would
  // just be noise.
  function archenemyRowHtml(isHost) {
    const fmt = (gameFormats || []).find((f) => f.name === game.game_format);
    if (!fmt || !(fmt.variants || []).includes('archenemy')) return '';
    const current = game.archenemy_id || game.host_id;
    return `
      <div class="mp-option-row" title="Regel 904: Der Archenemy spielt gegen den Rest des Tisches, mit eigenem Schema-Deck und 40 Leben.">
        <label for="mp-archenemy">Archenemy</label>
        <select id="mp-archenemy" ${isHost && !busy ? '' : 'disabled'}>
          ${game.seats
            .map(
              (s) =>
                `<option value="${escapeAttr(s.player_id)}"${s.player_id === current ? ' selected' : ''}>${escapeHtml(s.name)}</option>`,
            )
            .join('')}
        </select>
        ${isHost ? '' : '<span class="hint">Nur der Host kann das ändern.</span>'}
      </div>`;
  }

  function wireSetup() {
    setupRoot.querySelector('#mp-create')?.addEventListener('click', createGame);
    setupRoot.querySelector('#mp-new-name')?.addEventListener('input', (e) => {
      newGameName = e.target.value; // no re-render: don't steal focus mid-typing
    });
    setupRoot.querySelector('#mp-new-seats')?.addEventListener('change', (e) => {
      newGameSeats = Number(e.target.value) || 2;
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
      .querySelector('#mp-seats')
      ?.addEventListener('change', (e) => changeSeatCount(e.target.value));
    setupRoot
      .querySelector('#mp-mulligan')
      ?.addEventListener('change', (e) => changeMulliganStyle(e.target.value));
    setupRoot
      .querySelector('#mp-format')
      ?.addEventListener('change', (e) => changeGameFormat(e.target.value));
    setupRoot
      .querySelector('#mp-archenemy')
      ?.addEventListener('change', (e) => changeArchenemy(e.target.value));
    setupRoot
      .querySelector('#mp-takebacks')
      ?.addEventListener('change', (e) => changeTakebacksPerPlayer(e.target.value));
    setupRoot
      .querySelector('#mp-random-seating')
      ?.addEventListener('change', (e) => changeRandomization({ randomizeSeating: e.target.checked }));
    setupRoot
      .querySelector('#mp-random-start')
      ?.addEventListener('change', (e) => changeRandomization({ randomStartingPlayer: e.target.checked }));
    setupRoot.querySelector('#mp-ready')?.addEventListener('click', () => {
      const mySeat = game?.seats.find((s) => s.player_id === playerId);
      toggleReady(!mySeat?.ready);
    });
    setupRoot.querySelector('#mp-bot-kind')?.addEventListener('change', (e) => {
      botKindToAdd = e.target.value;
      renderSetup(); // the hint under the picker describes the chosen bot
    });
    setupRoot
      .querySelector('#mp-add-bot')
      ?.addEventListener('click', () => addBot(botKindToAdd || botKinds?.[0]?.kind));
    setupRoot.querySelectorAll('[data-bot-deck]').forEach((el) => {
      el.addEventListener('change', () => chooseDeck(el.value, el.dataset.botDeck));
    });
    setupRoot.querySelectorAll('[data-remove-bot]').forEach((el) => {
      el.addEventListener('click', () => removeBot(el.dataset.removeBot));
    });
    setupRoot.querySelectorAll('[data-banner-toggle]').forEach((el) => {
      el.addEventListener('click', () => {
        const seatId = el.dataset.bannerToggle;
        bannerPickerFor = bannerPickerFor === seatId ? null : seatId;
        renderSetup();
      });
    });
    setupRoot.querySelectorAll('[data-banner-set]').forEach((el) => {
      el.addEventListener('click', () =>
        chooseBannerColor(el.dataset.bannerColor, el.dataset.bannerSet),
      );
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
    if (summary && showSummary && view?.state?.game_over) {
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
    const mulliganCount = setup.mulligan_count;
    const bottomCount = setup.bottom_count;
    const iAmDone = !setup.waiting_for.includes(playerId);
    const canKeep = mulliganBottom.size === bottomCount;
    const noMulligans = view.legal_actions.every((a) => a.type !== 'mulligan');
    const nextHand = setup.next_hand_size ?? 7;

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
            mulliganCount === 0
              ? `Deine Starthand: ${me.hand.length} Karten.${noMulligans ? ' In diesem Spiel wird ohne Mulligan gespielt.' : ' Behalten, oder neu mischen (Mulligan)?'}`
              : mulliganText(setup, mulliganCount, bottomCount, me.hand.length)
          }
        </p>
        ${statusHtml()}
        <div class="card-grid gf-mulligan-hand">
          ${me.hand.map((o) => mulliganCardHtml(o, bottomCount)).join('')}
        </div>
        <div class="gf-controls">
          ${noMulligans ? '' : `<button id="mp-mulligan" type="button" ${busy ? 'disabled' : ''}>🔀 Mulligan (${nextHand} Karten ziehen)</button>`}
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
    return mulliganTileHtml(o, {
      imageCache: getState().imageCache,
      selected: mulliganBottom.has(o.instance_id),
      bottomEnabled: bottomCount > 0,
    });
  }

  function toggleBottomCard(instanceId) {
    const bottomCount = view?.setup?.bottom_count || 0;
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
    boardRoot.innerHTML = `
      <div class="goldfish-summary">
        <h3>Partie-Auswertung</h3>
        ${resultBannerHtml(s, playerId)}
        ${analysisHtml(summary.analysis)}
        <div class="gf-controls">
          <button id="mp-summary-board" type="button">🔍 Spielfeld ansehen</button>
          <button id="mp-summary-leave" type="button" class="primary">✖ Spiel schließen</button>
        </div>
      </div>`;
    boardRoot.querySelector('#mp-summary-board')?.addEventListener('click', () => {
      showSummary = false;
      renderBoard();
    });
    boardRoot.querySelector('#mp-summary-leave')?.addEventListener('click', closeGame);
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
