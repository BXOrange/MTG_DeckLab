// "Solo gegen Bots" tab: play a saved deck against 1–3 bots on the real
// Multiplayer rules engine — genuine turns, the stack, RULE 117 priority,
// hidden opponent hands — but with no lobby, no socket, no other humans.
// Backend: mtg_analyzer/api/solo.py (a thin REST surface over the same
// GameSession/bots machinery api/multiplayer.py uses).
//
// The deck/opponent picker and mulligan screen below are solo-specific;
// the interactive board (once a hand is kept) is the shared
// gameBoardView.js — the same one Goldfisch, Replay and Multiplayer use —
// given a multiplayer-style transport (every action is the human seat's,
// and the bots have already answered by the time the reply comes back).

import {
  startSolo,
  sendSoloAction,
  concedeSolo,
  restartSolo,
  endSolo,
  exportReplay,
  listSavedDecks,
  getDeckValidation,
  listFavoriteDecks,
  fetchGameFormats,
  fetchBotKinds,
  fetchDeckTokens,
  listTokenImages,
  tokenImageUrl,
  sleeveImageUrl,
} from './api.js';
import { getPlayerName } from './settings.js';
import { getState, setState } from './state.js';
import { preloadCardImages, cacheResolvedCard } from './cardImages.js';
import { parseDeckSections } from './parser.js';
import { createGameBoardView } from './gameBoardView.js';
import { analysisHtml } from './gameStats.js';
import { mulliganText } from './mulligan.js';
import {
  escapeHtml,
  escapeAttr,
  deckSelectOptionsHtml,
  formatSelectOptionsHtml,
  mulliganTileHtml,
  resultBannerHtml,
  loadUnmodeledDeckIds,
} from './gameSetup.js';

const MAX_OPPONENTS = 3;

/**
 * Persistent "Solo gegen Bots" controller. Its session survives across
 * `mount()` calls (tab switches) so navigating away doesn't drop the game.
 */
export function createSoloView() {
  let sessionId = null;
  let view = null;
  let status = '';
  let statusKind = '';
  let busy = false;
  let root = null;

  // 'pick' → 'loading' → 'mulligan' → 'playing' → 'summary'.
  let phase = 'pick';
  let loadingProgress = { loaded: 0, total: 0 };
  let mulliganBottom = new Set();
  let summary = null; // { analysis, state } kept after the session is gone

  // Deck / opponents picker.
  let savedDecks = null;
  let decksLoading = false;
  let decksLoadError = false;
  let selectedDeckId = '';
  let selectedValidation = null;
  let validating = false;
  let favoriteDeckIds = new Set();
  //: Saved-deck ids holding cards the engine doesn't model yet — drives the
  //: "⚠️" marker in the deck picker (own deck + opponent decks). Filled
  //: asynchronously after the deck list loads.
  let unmodeledDeckIds = new Set();
  let gameFormats = null;
  let selectedFormat = 'commander';
  let botKinds = null;
  // One row per bot opponent: { kind, deckId }. deckId '' → mirror-matches
  // the human's deck at start.
  let opponents = [{ kind: '', deckId: '' }];
  let startingPlayer = 'you'; // 'you' | 'random'

  const board = createGameBoardView({
    // Solo speaks the same shape Multiplayer's transport does: the POST
    // reply already carries the position *after* the bots have answered, so
    // (unlike Multiplayer, which waits for a socket push) we hand that view
    // straight back for the board to repaint from.
    transport: {
      sendAction: async (action) => {
        if (!sessionId) return { ok: false, status: 0, data: null };
        const res = await sendSoloAction(sessionId, action);
        return { ok: res.ok, status: res.status, data: res.ok ? res.data : null, detail: res.data };
      },
    },
    // Interactive priority → "Passen", not "Zug weiter"; one shared
    // timeline with the bots → no per-move rewind (only a full restart).
    allowRewind: false,
    allowFastForward: false,
    onViewChange: (v) => {
      if (v) view = v;
    },
    // `boardBusy` is the board's own "an action is in flight" flag — use it
    // for the disabled state (our own `busy` only tracks the pre-game
    // screens, and the board doesn't re-render when it flips back). Re-entry
    // into restart/export/concede is guarded inside those handlers instead.
    extraControls: (boardBusy) => {
      const controls = [
        { id: 'restart', label: '⟲ Neu starten', disabled: boardBusy || busy, onClick: restart },
        {
          id: 'export',
          label: '⬇ Als Replay speichern',
          title: 'Diesen Spielzustand als Replay-Datei speichern (im Replay-Tab wieder ladbar)',
          disabled: boardBusy || busy,
          onClick: exportReplayFile,
        },
      ];
      if (!view?.state?.game_over) {
        controls.push({
          id: 'concede',
          label: '🏳️ Aufgeben',
          title: 'Die Partie aufgeben (Regel 104.3a) und die Auswertung ansehen',
          disabled: boardBusy,
          onClick: concede,
        });
      }
      controls.push({ id: 'quit', label: 'Beenden', onClick: quit });
      return controls;
    },
    // No lobby → connection state comes from the game state itself (the
    // bots are always "present"); the banner colour the server derived from
    // each seat's deck identity rides along on the player object.
    seatStatus: (id) => {
      const p = view?.state?.players?.find((x) => x.id === id);
      return p ? { connected: true, banner_color: p.banner_color || null } : null;
    },
  });

  function mount(el) {
    root = el;
    board.mount(el);
    if (!view) {
      if (savedDecks === null) loadDecks();
      if (gameFormats === null) loadFormats();
      if (botKinds === null) loadBotKinds();
    }
    render();
  }

  function onShown() {
    if (!view) {
      loadDecks();
      if (gameFormats === null) loadFormats();
      if (botKinds === null) loadBotKinds();
    }
  }

  function setStatus(text, kind = '') {
    status = text;
    statusKind = kind;
  }

  // --- Loading pick-screen data ----------------------------------------

  async function loadDecks() {
    decksLoading = true;
    render();
    const playerName = getPlayerName();
    const [decks, favorites] = await Promise.all([
      listSavedDecks(),
      playerName ? listFavoriteDecks(playerName) : Promise.resolve([]),
    ]);
    decksLoading = false;
    decksLoadError = decks === null;
    savedDecks = decks || [];
    favoriteDeckIds = new Set(favorites || []);
    if (selectedDeckId && !savedDecks.some((d) => d.id === selectedDeckId)) {
      selectedDeckId = '';
      selectedValidation = null;
    }
    render();
    // Coverage marker — non-blocking, repaints once the checks land.
    loadUnmodeledDeckIds(savedDecks).then((ids) => {
      unmodeledDeckIds = ids;
      if (ids.size) render();
    });
  }

  async function loadFormats() {
    const res = await fetchGameFormats();
    gameFormats = res.ok ? res.data?.formats || [] : [];
    if (res.ok && res.data?.default) selectedFormat = res.data.default;
    render();
  }

  async function loadBotKinds() {
    botKinds = [];
    const res = await fetchBotKinds();
    botKinds = res.ok ? res.data?.bots || [] : [];
    // Default every empty row to the first kind (usually the Goldfisch-Bot).
    if (botKinds.length) {
      for (const row of opponents) if (!row.kind) row.kind = botKinds[0].kind;
    }
    render();
  }

  async function selectDeck(deckId) {
    selectedDeckId = deckId;
    selectedValidation = null;
    if (!deckId) {
      render();
      return;
    }
    validating = true;
    render();
    selectedValidation = await getDeckValidation(deckId);
    validating = false;
    render();
  }

  // --- Opponent rows -------------------------------------------------------

  function addOpponent() {
    if (opponents.length >= MAX_OPPONENTS) return;
    opponents = [...opponents, { kind: botKinds?.[0]?.kind || '', deckId: '' }];
    render();
  }

  function removeOpponent(index) {
    if (opponents.length <= 1) return;
    opponents = opponents.filter((_, i) => i !== index);
    render();
  }

  function setOpponent(index, patch) {
    opponents = opponents.map((row, i) => (i === index ? { ...row, ...patch } : row));
  }

  // --- Starting a game --------------------------------------------------

  async function start() {
    if (!selectedDeckId) {
      setStatus('Bitte zuerst dein Deck auswählen.', 'warning');
      render();
      return;
    }
    if (!selectedValidation?.isLegal) {
      setStatus('Nur legale Decks können ein Solo-Spiel starten.', 'warning');
      render();
      return;
    }
    const rows = opponents.map((row) => ({
      kind: row.kind || botKinds?.[0]?.kind || 'goldfish',
      deckId: row.deckId || selectedDeckId, // mirror match by default
    }));

    phase = 'loading';
    loadingProgress = { loaded: 0, total: 0 };
    setStatus('Kartenbilder werden geladen …', 'pending');
    render();
    await preloadAllArt(rows);

    await withBusy('Spiel wird gestartet …', async () => {
      const res = await startSolo({
        deckId: selectedDeckId,
        opponents: rows,
        gameFormat: selectedFormat,
        startingPlayer,
      });
      if (res.ok) {
        applyView(res.data);
        setStatus('Wähle deine Starthand: behalten oder Mulligan.', 'ok');
      } else if (res.status === 422) {
        phase = 'pick';
        const detail = res.data?.detail || {};
        const reason = (detail.errors || []).join(' ') || detail.message || 'Deck ist nicht legal.';
        setStatus(`Start abgelehnt: ${reason}`, 'warning');
      } else if (res.status === 400) {
        phase = 'pick';
        setStatus(`Start abgelehnt: ${detailText(res)}`, 'warning');
      } else if (res.status === 0) {
        phase = 'pick';
        setStatus('Server nicht erreichbar.', 'warning');
      } else {
        phase = 'pick';
        setStatus(`Start fehlgeschlagen (${res.status}).`, 'warning');
      }
    });
  }

  // Preload every seat's card art (all decks) + the human deck's producible
  // token art, so nothing pops in mid-game. Best-effort — a failed fetch
  // just means it lazy-loads later.
  async function preloadAllArt(rows) {
    const deckIds = new Set([selectedDeckId, ...rows.map((r) => r.deckId)]);
    const names = new Set();
    for (const id of deckIds) {
      const deck = savedDecks?.find((d) => d.id === id);
      if (!deck) continue;
      for (const c of parseDeckSections(deck).allCards) names.add(c.name);
    }
    const merged = new Map(getState().imageCache);
    if (names.size) {
      const resolved = await preloadCardImages(Array.from(names), (loaded, total) => {
        loadingProgress = { loaded, total };
        render();
      });
      for (const [name, entry] of resolved) merged.set(name, entry);
    }
    await preloadDeckTokens(merged);
    setState({ imageCache: merged });
    await loadPlayerAssets();
  }

  async function preloadDeckTokens(merged) {
    const res = await fetchDeckTokens({ deckId: selectedDeckId });
    const tokens = res.ok ? res.data?.tokens || [] : [];
    for (const t of tokens) {
      const key = (t.name || '').toLowerCase();
      if (!key || merged.has(key)) continue;
      const entry = { small: t.image_small || null, normal: t.image_normal || null, card: t };
      merged.set(key, entry);
      cacheResolvedCard(key, entry);
    }
    const urls = tokens.map((t) => t.image_small).filter(Boolean);
    if (!urls.length) return;
    const base = loadingProgress.total;
    let loaded = base;
    loadingProgress = { loaded, total: base + urls.length };
    render();
    await Promise.all(
      urls.map(
        (url) =>
          new Promise((resolve) => {
            const img = new Image();
            img.onload = img.onerror = () => {
              loaded += 1;
              loadingProgress = { loaded, total: base + urls.length };
              render();
              resolve();
            };
            img.src = url;
          }),
      ),
    );
  }

  async function loadPlayerAssets() {
    const playerName = getPlayerName();
    if (!playerName) {
      board.setAssets({});
      return;
    }
    const images = await listTokenImages(playerName);
    const tokenImages = {};
    for (const t of images || []) {
      tokenImages[(t.token_name || '').toLowerCase()] = tokenImageUrl(playerName, t.token_name);
    }
    const deck = savedDecks?.find((d) => d.id === selectedDeckId);
    const sleeveUrl = deck?.sleeveId ? sleeveImageUrl(playerName, deck.sleeveId) : null;
    board.setAssets({ tokenImages, sleeveImageUrl: sleeveUrl });
  }

  // --- Setup-phase actions (mulligan / keep) --------------------------

  async function mulligan() {
    await act({ type: 'mulligan' });
  }

  async function keepHand() {
    const setup = view?.setup;
    if (!setup) return;
    if (mulliganBottom.size !== setup.bottom_count) {
      setStatus(`Bitte genau ${setup.bottom_count} Karte(n) zum Unterlegen auswählen.`, 'warning');
      render();
      return;
    }
    await act({ type: 'keep_hand', bottom_instance_ids: Array.from(mulliganBottom) });
  }

  function toggleBottomCard(instanceId) {
    const setup = view?.setup;
    if (!setup) return;
    if (mulliganBottom.has(instanceId)) mulliganBottom.delete(instanceId);
    else if (mulliganBottom.size < setup.bottom_count) mulliganBottom.add(instanceId);
    render();
  }

  async function act(action) {
    if (!sessionId) return;
    await withBusy('…', async () => {
      const res = await sendSoloAction(sessionId, action);
      if (res.ok) {
        applyView(res.data);
        setStatus('', '');
      } else if (res.status === 400) {
        setStatus(`Aktion nicht erlaubt: ${res.data?.detail ?? ''}`, 'warning');
      } else if (res.status === 404) {
        setStatus('Spielsitzung abgelaufen – bitte neu starten.', 'warning');
        sessionId = null;
        view = null;
        phase = 'pick';
      } else {
        setStatus(`Fehler (${res.status}).`, 'warning');
      }
    });
  }

  async function concede() {
    if (!sessionId || busy || !window.confirm('Wirklich aufgeben? Das beendet die Partie.')) return;
    await withBusy('Aufgeben …', async () => {
      const res = await concedeSolo(sessionId);
      if (res.ok) {
        view = res.data;
        summary = { analysis: res.data.analysis, state: res.data.state };
        board.stop();
        phase = 'summary';
      } else {
        setStatus(`Aufgeben fehlgeschlagen (${res.status}).`, 'warning');
      }
    });
    render();
  }

  async function restart() {
    if (!sessionId || busy) return;
    await withBusy('Spiel wird neu gestartet …', async () => {
      const res = await restartSolo(sessionId);
      if (res.ok) {
        summary = null;
        applyView(res.data);
        setStatus('Spiel neu gestartet.', 'ok');
      } else {
        setStatus(`Neustart fehlgeschlagen (${res.status}).`, 'warning');
      }
    });
  }

  async function exportReplayFile() {
    if (!sessionId || busy) return;
    const res = await exportReplay(sessionId);
    if (!res.ok || !res.data) {
      setStatus(`Export fehlgeschlagen (${res.status}).`, 'warning');
      render();
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
    render();
  }

  async function quit() {
    const id = sessionId;
    summary = view ? { analysis: view.analysis, state: view.state } : null;
    board.stop();
    sessionId = null;
    view = null;
    phase = summary ? 'summary' : 'pick';
    setStatus('', '');
    render();
    if (id) await endSolo(id);
  }

  function applyView(data) {
    sessionId = data.session_id;
    view = data;
    const setupDone = data.setup ? data.setup.complete : true;
    if (!setupDone) {
      phase = 'mulligan';
      mulliganBottom = new Set();
    } else {
      phase = 'playing';
      board.start(sessionId, data);
    }
    if (data.state?.game_over && !summary) {
      summary = { analysis: data.analysis, state: data.state };
    }
  }

  async function withBusy(pendingText, fn) {
    busy = true;
    setStatus(pendingText, 'pending');
    render();
    try {
      await fn();
    } finally {
      busy = false;
      render();
    }
  }

  // --- Rendering -----------------------------------------------------------

  function render() {
    if (!root) return;
    if (phase === 'loading') renderLoadingScreen();
    else if (phase === 'mulligan') renderMulligan();
    else if (phase === 'playing') {
      // The shared board repaints itself on every action.
    } else if (phase === 'summary' && summary) renderSummary();
    else renderStartPanel();
  }

  function renderLoadingScreen() {
    const { loaded, total } = loadingProgress;
    const pct = total ? Math.round((loaded / total) * 100) : 100;
    root.innerHTML = `
      <div class="goldfish-loading">
        <h3>Spiel wird vorbereitet …</h3>
        <p class="hint">Kartenbilder aller Decks werden geladen, damit beim Start alles sofort da ist.</p>
        <div class="gf-loading-bar"><div class="gf-loading-fill" style="width: ${pct}%"></div></div>
        <p class="server-status pending">${total ? `${loaded} / ${total} Bilder geladen …` : 'Lädt …'}</p>
      </div>`;
  }

  function renderStartPanel() {
    const legal = selectedValidation?.isLegal === true;
    const canStart = !!selectedDeckId && legal && !busy && opponents.length >= 1;
    root.innerHTML = `
      <div class="goldfish-start">
        <h3>Solo gegen Bots</h3>
        <p class="hint">
          Spiele ein gespeichertes Deck gegen 1–3 Bots auf der echten
          Regel-Engine: echte Gegnerzüge, Stack, Priorität, verdeckte
          Handkarten. Ohne Lobby, ohne Mitspieler. Nur legale Decks können
          starten.
        </p>

        <div class="gf-deck-picker">
          <label for="solo-deck-select">Dein Deck</label>
          <select id="solo-deck-select" ${decksLoading ? 'disabled' : ''}>
            ${deckSelectOptionsHtml({
              savedDecks,
              selectedId: selectedDeckId,
              favoriteDeckIds,
              unmodeledDeckIds,
              decksLoading,
              decksLoadError,
              errorText: '— Server nicht erreichbar (⟳ erneut versuchen) —',
            })}
          </select>
          <button id="solo-refresh-decks" type="button" title="Deckliste neu laden">⟳</button>
        </div>

        <div class="gf-deck-picker">
          <label for="solo-format-select">Format</label>
          <select id="solo-format-select" ${gameFormats === null ? 'disabled' : ''}>
            ${formatSelectOptionsHtml(gameFormats, selectedFormat)}
          </select>
        </div>

        ${deckLegalityHtml()}

        <fieldset class="solo-opponents">
          <legend>Gegner</legend>
          ${opponents.map((row, i) => opponentRowHtml(row, i)).join('')}
          ${
            opponents.length < MAX_OPPONENTS
              ? `<button id="solo-add-opponent" type="button" ${busy ? 'disabled' : ''}>+ Gegner hinzufügen</button>`
              : ''
          }
        </fieldset>

        <div class="gf-deck-picker">
          <label for="solo-start-who">Wer beginnt?</label>
          <select id="solo-start-who" ${busy ? 'disabled' : ''}>
            <option value="you"${startingPlayer === 'you' ? ' selected' : ''}>Du (auf dem Spiel)</option>
            <option value="random"${startingPlayer === 'random' ? ' selected' : ''}>Zufällig</option>
          </select>
        </div>

        <button id="solo-start-btn" type="button" class="primary" ${canStart ? '' : 'disabled'}>
          Solo-Spiel starten
        </button>
        ${statusHtml()}
      </div>`;

    root.querySelector('#solo-deck-select')?.addEventListener('change', (e) => selectDeck(e.target.value));
    root.querySelector('#solo-refresh-decks')?.addEventListener('click', loadDecks);
    root.querySelector('#solo-format-select')?.addEventListener('change', (e) => {
      selectedFormat = e.target.value;
    });
    root.querySelector('#solo-start-who')?.addEventListener('change', (e) => {
      startingPlayer = e.target.value;
    });
    root.querySelector('#solo-add-opponent')?.addEventListener('click', addOpponent);
    root.querySelectorAll('[data-opp-kind]').forEach((el) => {
      el.addEventListener('change', () => setOpponent(Number(el.dataset.oppKind), { kind: el.value }));
    });
    root.querySelectorAll('[data-opp-deck]').forEach((el) => {
      el.addEventListener('change', () => setOpponent(Number(el.dataset.oppDeck), { deckId: el.value }));
    });
    root.querySelectorAll('[data-opp-remove]').forEach((el) => {
      el.addEventListener('click', () => removeOpponent(Number(el.dataset.oppRemove)));
    });
    root.querySelector('#solo-start-btn')?.addEventListener('click', start);
  }

  function opponentRowHtml(row, index) {
    const kindOptions = (botKinds || [])
      .map(
        (b) =>
          `<option value="${escapeAttr(b.kind)}"${b.kind === row.kind ? ' selected' : ''}>${escapeHtml(b.label)}</option>`,
      )
      .join('') || '<option value="goldfish">Goldfisch-Bot</option>';
    const chosen = (botKinds || []).find((b) => b.kind === row.kind);
    return `
      <div class="solo-opponent-row">
        <span class="solo-opponent-idx">🤖 ${index + 1}</span>
        <select data-opp-kind="${index}" ${busy ? 'disabled' : ''}>${kindOptions}</select>
        <select data-opp-deck="${index}" ${busy ? 'disabled' : ''}>
          ${deckSelectOptionsHtml({
            savedDecks,
            selectedId: row.deckId,
            favoriteDeckIds,
            unmodeledDeckIds,
            decksLoading,
            decksLoadError,
            placeholder: '— wie dein Deck —',
          })}
        </select>
        ${
          opponents.length > 1
            ? `<button type="button" data-opp-remove="${index}" title="Gegner entfernen" ${busy ? 'disabled' : ''}>✕</button>`
            : ''
        }
        ${chosen?.description ? `<span class="hint">${escapeHtml(chosen.description)}</span>` : ''}
      </div>`;
  }

  function deckLegalityHtml() {
    if (!selectedDeckId) return '';
    if (validating) return '<p class="server-status pending">Prüfe Legalität …</p>';
    if (selectedValidation === null) {
      return '<p class="server-status warning">Legalität konnte nicht geprüft werden (Server?).</p>';
    }
    if (selectedValidation.isLegal) return '<p class="server-status ok">✅ Deck ist legal.</p>';
    const reasons = (selectedValidation.errors || []).map((e) => `<li>${escapeHtml(e)}</li>`).join('');
    return `
      <div class="server-status warning">🛑 Deck ist nicht legal – Start nicht möglich.</div>
      ${reasons ? `<ul class="issue-list validation-errors">${reasons}</ul>` : ''}`;
  }

  function renderMulligan() {
    const setup = view.setup || { complete: false, mulligan_count: 0, bottom_count: 0 };
    const me = view.state.players.find((p) => p.id === view.perspective) || view.state.players[0];
    const mulliganCount = setup.mulligan_count;
    const bottomCount = setup.bottom_count;
    const canKeep = mulliganBottom.size === bottomCount;
    const nextHand = setup.next_hand_size ?? 7;
    const noMulligans = (view.legal_actions || []).every((a) => a.type !== 'mulligan');
    root.innerHTML = `
      <div class="goldfish-mulligan">
        <h3>Starthand</h3>
        <p class="hint">
          ${
            mulliganCount === 0
              ? `Deine Starthand: ${me.hand.length} Karten.${noMulligans ? ' In diesem Spiel wird ohne Mulligan gespielt.' : ' Behalten, oder neu mischen (Mulligan)?'}`
              : mulliganText(setup, mulliganCount, bottomCount, me.hand.length) +
                (bottomCount > 0 ? ' Wähle sie unten aus.' : '')
          }
        </p>
        ${statusHtml()}
        <div class="card-grid gf-mulligan-hand">
          ${me.hand
            .map((o) =>
              mulliganTileHtml(o, {
                imageCache: getState().imageCache,
                selected: mulliganBottom.has(o.instance_id),
                bottomEnabled: bottomCount > 0,
              }),
            )
            .join('')}
        </div>
        <div class="gf-controls">
          ${noMulligans ? '' : `<button id="solo-mulligan-btn" type="button" ${busy ? 'disabled' : ''}>🔀 Mulligan (${nextHand} Karten ziehen)</button>`}
          <button id="solo-keep-btn" type="button" class="primary" ${busy || !canKeep ? 'disabled' : ''}>
            ${bottomCount === 0 ? 'Hand behalten' : `Behalten (${mulliganBottom.size}/${bottomCount} unten ausgewählt)`}
          </button>
          <button id="solo-quit-mulligan" type="button" ${busy ? 'disabled' : ''}>Abbrechen</button>
        </div>
      </div>`;
    root.querySelector('#solo-mulligan-btn')?.addEventListener('click', mulligan);
    root.querySelector('#solo-keep-btn')?.addEventListener('click', keepHand);
    root.querySelector('#solo-quit-mulligan')?.addEventListener('click', quit);
    root.querySelectorAll('[data-bottom-toggle]').forEach((el) => {
      el.addEventListener('click', () => toggleBottomCard(Number(el.dataset.bottomToggle)));
    });
  }

  function renderSummary() {
    const s = summary.state;
    const meId = view?.perspective || s?.players?.find((p) => p.id?.startsWith('solo:'))?.id || null;
    root.innerHTML = `
      <div class="goldfish-summary">
        <h3>Partie-Auswertung</h3>
        ${s && s.game_over ? resultBannerHtml(s, meId) : `<p class="hint">Partie nach ${summary.analysis?.turns ?? 0} Zügen beendet.</p>`}
        ${analysisHtml(summary.analysis)}
        <div class="gf-controls">
          <button id="solo-summary-new" type="button" class="primary">Neues Spiel</button>
        </div>
      </div>`;
    root.querySelector('#solo-summary-new')?.addEventListener('click', () => {
      const id = sessionId;
      sessionId = null;
      view = null;
      summary = null;
      phase = 'pick';
      loadDecks();
      render();
      if (id) endSolo(id); // best-effort cleanup of the finished session
    });
  }

  function statusHtml() {
    if (!status) return '';
    return `<p class="server-status ${statusKind}">${escapeHtml(status)}</p>`;
  }

  function detailText(res) {
    const detail = res.data?.detail;
    if (!detail) return `Fehler (${res.status}).`;
    return typeof detail === 'string' ? detail : detail.message || `Fehler (${res.status}).`;
  }

  return { mount, onShown };
}
