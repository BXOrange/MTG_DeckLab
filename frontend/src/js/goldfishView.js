// "Goldfisch" tab: play a saved deck against the real backend rules engine
// (mtg_analyzer/game/) via the /api/game session endpoints. Every move
// here is validated server-side and the board shown is the server's
// authoritative GameState. Supports advancing the turn step by step,
// playing/tapping/casting/attacking from the server's legal_actions, and —
// the point of a goldfish — restarting and rewinding at any time (UC3).
//
// The deck picker, card-image preload, and mulligan screens below are
// goldfish-specific; the actual interactive board (once a hand is kept) is
// the shared `gameBoardView.js`, also driving Replay/Puzzle mode's play mode.

import { getState, setState } from './state.js';
import {
  startGoldfish,
  fetchDeckTokens,
  sendGameAction,
  restartGame,
  endGame,
  listSavedDecks,
  getDeckValidation,
  exportReplay,
  listTokenImages,
  tokenImageUrl,
  sleeveImageUrl,
  fetchGameFormats,
  listFavoriteDecks,
} from './api.js';
import { getPlayerName } from './settings.js';
import { preloadCardImages, cacheResolvedCard } from './cardImages.js';
import { parseDeckSections } from './parser.js';
import { createGameBoardView } from './gameBoardView.js';
import { analysisHtml } from './gameStats.js';
import { mulliganText } from './mulligan.js';
import {
  escapeHtml,
  deckSelectOptionsHtml,
  formatSelectOptionsHtml,
  mulliganTileHtml,
  loadUnmodeledDeckIds,
} from './gameSetup.js';
import { t } from './i18n.js';

/**
 * Create a persistent goldfish controller. Its session survives across
 * `mount()` calls (e.g. switching tabs and back) so navigating away
 * doesn't drop the running game.
 */
export function createGoldfishView() {
  let sessionId = null;
  let view = null; // last session view from the server
  let status = '';
  let statusKind = '';
  let busy = false;
  let root = null;

  // Which screen to show: 'pick' (deck picker) -> 'loading' (preloading
  // card art) -> 'mulligan' (setup phase: keep or mulligan the opening
  // hand) -> 'playing' (the shared interactive board, driven by `board`).
  let phase = 'pick';
  let loadingProgress = { loaded: 0, total: 0 };
  // Cards picked to put on the bottom of the library when keeping a
  // mulliganed hand (London mulligan) — instance ids, cleared whenever a
  // fresh view enters/re-enters the mulligan phase.
  let mulliganBottom = new Set();
  // The end-of-match review, kept after the session is torn down so
  // "Beenden" lands on a stats screen instead of the empty deck picker.
  // `{ analysis, state }` (a snapshot of the last view) or null.
  let summary = null;
  // Setup option (UC3): whether the human draws on turn 1 ("on the draw")
  // instead of skipping it ("on the play", the default). Sent with keep_hand.
  let drawFirst = false;

  // Deck picker state (start panel): the saved decks to choose from, the
  // selected id, and that deck's legality — only legal decks may start.
  let savedDecks = null; // null = not loaded yet
  let decksLoading = false;
  // VIS-1: distinct from "loaded, zero decks" — otherwise a network failure
  // silently rendered as "— keine gespeicherten Decks —" with no indication
  // anything went wrong.
  let decksLoadError = false;
  let selectedDeckId = '';
  let selectedValidation = null; // {isLegal, errors, ...} | null
  let validating = false;
  //: This player's starred deck ids (Profil tab) — sorts the picker above,
  //: favorites first. Fetched alongside the deck list; empty when no player
  //: name is set (there's nothing to key favorites by).
  let favoriteDeckIds = new Set();
  //: Saved-deck ids that hold cards the engine doesn't model yet — drives the
  //: "⚠️" marker in the picker. Filled asynchronously after the deck list
  //: loads (one coverage check per deck), so the picker shows without waiting.
  let unmodeledDeckIds = new Set();
  //: PLR-13: the RULE 8/9 format this goldfish game starts in (GET
  //: /api/game/formats), 'commander' until the catalogue has loaded.
  let gameFormats = null; // null = not loaded yet
  let selectedFormat = 'commander';

  // The shared interactive board (advance/cast/attack/tap/stack/rewind).
  // "Neu starten" isn't one of its built-ins — a goldfish restart can land
  // back in the mulligan phase, which the board doesn't know how to draw —
  // so it's supplied here, alongside the goldfish-only export/quit buttons.
  const board = createGameBoardView({
    onViewChange: (v) => {
      view = v;
    },
    extraControls: () => [
      {
        id: 'restart',
        label: t('play.restart'),
        disabled: busy,
        onClick: restart,
      },
      {
        id: 'export',
        label: t('play.saveReplay'),
        title: t('play.saveReplayTitle'),
        disabled: busy,
        onClick: exportReplayFile,
      },
      { id: 'quit', label: t('play.quit'), onClick: quit },
    ],
  });

  function mount(el) {
    root = el;
    board.mount(el);
    if (!view && savedDecks === null) loadDecks();
    if (!view && gameFormats === null) loadFormats();
    render();
  }

  // Called when the Goldfisch tab is (re)opened — refresh the deck list
  // so newly-saved decks appear, but don't disturb a running game.
  function onShown() {
    if (!view) loadDecks();
    if (!view && gameFormats === null) loadFormats();
  }

  function setStatus(text, kind = '') {
    status = text;
    statusKind = kind;
  }

  // --- Deck picker --------------------------------------------------------

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
    // Keep a valid selection; validate it if still present.
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

  // PLR-13: the format catalogue for the picker (GET /api/game/formats) —
  // deck-independent, fetched once per mount like `loadDecks`.
  async function loadFormats() {
    const res = await fetchGameFormats();
    gameFormats = res.ok ? res.data?.formats || [] : [];
    if (res.ok && res.data?.default) selectedFormat = res.data.default;
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
    const validation = await getDeckValidation(deckId);
    validating = false;
    selectedValidation = validation; // null on failure
    render();
  }

  async function start() {
    if (!selectedDeckId) {
      setStatus(t('goldfish.mustPickDeck'), 'warning');
      render();
      return;
    }
    if (!selectedValidation?.isLegal) {
      setStatus(t('goldfish.needLegal'), 'warning');
      render();
      return;
    }

    // Preload every card image before the board ever renders, so nothing
    // pops in mid-game — the actual cause of "images not always loaded".
    phase = 'loading';
    loadingProgress = { loaded: 0, total: 0 };
    setStatus(t('play.loadingImages'), 'pending');
    render();
    const deck = savedDecks?.find((d) => d.id === selectedDeckId);
    if (deck) {
      const names = parseDeckSections(deck).allCards.map((c) => c.name);
      const resolved = await preloadCardImages(names, (loaded, total) => {
        loadingProgress = { loaded, total };
        render();
      });
      const merged = new Map(getState().imageCache);
      for (const [name, entry] of resolved) merged.set(name, entry);
      // Also preload the art of every token this deck can *produce* (created
      // by effects mid-game, never named in the decklist) so a token renders
      // instantly instead of popping in the first time it's made.
      await preloadDeckTokens(merged);
      setState({ imageCache: merged });
    }
    await loadPlayerAssets(deck);

    await withBusy(t('play.starting'), async () => {
      const res = await startGoldfish({ deckId: selectedDeckId, shuffle: true, gameFormat: selectedFormat });
      if (res.ok) {
        applyView(res.data);
        const notFound = res.data.notFound || [];
        setStatus(
          notFound.length
            ? t('play.startedNotResolvable', { names: notFound.join(', ') })
            : t('play.pickHand'),
          notFound.length ? 'warning' : 'ok'
        );
      } else if (res.status === 422) {
        phase = 'pick';
        const detail = res.data?.detail || {};
        const reason = (detail.errors || []).join(' ') || 'Deck ist nicht legal.';
        setStatus(`Start abgelehnt: ${reason}`, 'warning');
      } else if (res.status === 0) {
        phase = 'pick';
        setStatus('Server nicht erreichbar.', 'warning');
      } else {
        phase = 'pick';
        setStatus(`Start fehlgeschlagen (${res.status}).`, 'warning');
      }
    });
  }

  // Fetch the tokens the selected deck can produce and preload their art into
  // `merged` (the imageCache) — keyed primarily by the token's own id (see
  // `resolveImageUrl` in gameBoardView.js), plus lowercased name as a
  // secondary/tooltip-cache key — so a token GameObject shows its art the
  // instant an effect creates it. The backend's token-art library (a real
  // Scryfall id + art whenever one matches the token's exact name/P/T/colors,
  // `services/token_database.py`'s `TokenArtLibrary`) covers most vanilla
  // creature tokens too, not just the small curated-ability set (Treasure,
  // Clue, …); anything it doesn't cover still has no art and keeps the text
  // fallback. Best-effort: a failed fetch just means tokens lazy-load as before.
  async function preloadDeckTokens(merged) {
    const res = await fetchDeckTokens({ deckId: selectedDeckId });
    const tokens = res.ok ? res.data?.tokens || [] : [];
    if (!tokens.length) return;

    for (const t of tokens) {
      if (!t.image_small && !t.image_normal) continue;
      const entry = {
        small: t.image_small || null,
        normal: t.image_normal || null,
        card: t,
      };
      // Id first: unique per exact (name, power, toughness, colors) variant,
      // so two same-named tokens printed at different stats (e.g. several
      // "Shapeshifter" stat lines) each keep their own art instead of
      // whichever variant's entry happened to land last under a shared name.
      if (t.id) merged.set(t.id, entry);
      const key = (t.name || '').toLowerCase();
      // The by-name entry is a same-name fallback (and cardImages.js's own
      // tooltip-cache key) — first one in wins, and it never clobbers a real
      // deck card's already-resolved art under that same name.
      if (key && !merged.has(key)) {
        merged.set(key, entry);
        // Also seed cardImages.js's own cache — cardHoverDetail.js's tooltip
        // reads only that one, not this view's local `imageCache`, so without
        // this a token's hover detail stays stuck at "Lädt …" forever.
        cacheResolvedCard(key, entry);
      }
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
          })
      )
    );
  }

  // The local player's custom art (Einstellungen tab): token images by
  // name, plus the sleeve backside selected for this deck (Gespeicherte
  // Decks tab) — handed to the shared board so `resolveImageUrl` can use
  // them (see gameBoardView.js). Best-effort: a failed fetch just means
  // the board falls back to its default rendering.
  async function loadPlayerAssets(deck) {
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
    const sleeveUrl = deck?.sleeveId ? sleeveImageUrl(playerName, deck.sleeveId) : null;
    board.setAssets({ tokenImages, sleeveImageUrl: sleeveUrl });
  }

  async function mulligan() {
    await act({ type: 'mulligan' });
  }

  async function keepHand() {
    const setup = view?.setup;
    if (!setup) return;
    if (mulliganBottom.size !== setup.bottom_count) {
      setStatus(
        t('play.pickExactBottom', { count: setup.bottom_count }),
        'warning'
      );
      render();
      return;
    }
    await act({
      type: 'keep_hand',
      bottom_instance_ids: Array.from(mulliganBottom),
      draw_first: drawFirst,
    });
  }

  function toggleBottomCard(instanceId) {
    const setup = view?.setup;
    if (!setup) return;
    if (mulliganBottom.has(instanceId)) {
      mulliganBottom.delete(instanceId);
    } else if (mulliganBottom.size < setup.bottom_count) {
      mulliganBottom.add(instanceId);
    }
    render();
  }

  // Setup-phase-only actions (mulligan/keep_hand) — once the board is
  // playing, `board`'s own act() takes over.
  async function act(action) {
    if (!sessionId) return;
    await withBusy('…', async () => {
      const res = await sendGameAction(sessionId, action);
      if (res.ok) {
        applyView(res.data);
        setStatus('', '');
      } else if (res.status === 400) {
        setStatus(t('play.actionNotAllowed', { detail: res.data?.detail ?? '' }), 'warning');
      } else if (res.status === 404) {
        setStatus(t('play.sessionExpired'), 'warning');
        sessionId = null;
        view = null;
        phase = 'pick';
      } else {
        setStatus(t('play.error', { status: res.status }), 'warning');
      }
    });
  }

  // Reset to the opening state — for goldfish that always re-enters the
  // mulligan phase (`require_setup=True`), a screen the shared board
  // doesn't draw, so this stays goldfish's own rather than the board's.
  async function restart() {
    if (!sessionId) return;
    await withBusy(t('play.restarting'), async () => {
      const res = await restartGame(sessionId);
      if (res.ok) {
        applyView(res.data);
        setStatus(t('play.restarted'), 'ok');
      } else {
        setStatus(t('play.restartFailed', { status: res.status }), 'warning');
      }
    });
  }

  // Save the current goldfish position as a Replay-mode file (RULE-agnostic
  // board snapshot), so it can be re-opened and edited in the Replay tab.
  async function exportReplayFile() {
    if (!sessionId) return;
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
    // Keep the final stats digest so ending the match lands on a review
    // screen rather than dropping straight back to the deck picker. The
    // server session is still torn down below — the summary is client-side.
    summary = view ? { analysis: view.analysis, state: view.state } : null;
    sessionId = null;
    view = null;
    phase = summary ? 'summary' : 'pick';
    setStatus('', '');
    render();
    if (id) await endGame(id); // best-effort server cleanup
  }

  function applyView(data) {
    sessionId = data.session_id;
    view = data;
    const setupDone = data.setup ? data.setup.complete : true;
    phase = setupDone ? 'playing' : 'mulligan';
    if (!setupDone) {
      mulliganBottom = new Set();
    } else {
      board.start(sessionId, data);
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

  // --- Rendering ----------------------------------------------------------

  function render() {
    if (!root) return;
    if (phase === 'loading') {
      renderLoadingScreen();
    } else if (phase === 'mulligan') {
      renderMulligan();
    } else if (phase === 'playing') {
      // The shared board (`board`) repaints itself on every action; nothing
      // to do here beyond having called `board.start()` in `applyView`.
    } else if (phase === 'summary' && summary) {
      renderSummary();
    } else {
      renderStartPanel();
    }
  }

  function renderLoadingScreen() {
    const { loaded, total } = loadingProgress;
    const pct = total ? Math.round((loaded / total) * 100) : 100;
    root.innerHTML = `
      <div class="goldfish-loading">
        <h3>${t('play.preparing')}</h3>
        <p class="hint">${t('goldfish.loadingHint')}</p>
        <div class="gf-loading-bar"><div class="gf-loading-fill" style="width: ${pct}%"></div></div>
        <p class="server-status pending">${total ? escapeHtml(t('play.imagesLoaded', { loaded, total })) : t('play.loading')}</p>
      </div>
    `;
  }

  function renderStartPanel() {
    const legal = selectedValidation?.isLegal === true;
    const canStart = !!selectedDeckId && legal && !busy;
    root.innerHTML = `
      <div class="goldfish-start">
        <h3>${t('goldfish.heading')}</h3>
        <p class="hint">${escapeHtml(t('goldfish.intro'))}</p>

        <div class="gf-deck-picker">
          <label for="gf-deck-select">${t('play.deck')}</label>
          <select id="gf-deck-select" ${decksLoading ? 'disabled' : ''}>
            ${deckOptionsHtml()}
          </select>
          <button id="gf-refresh-decks" type="button" title="${escapeHtml(t('play.reloadDecks'))}">⟳</button>
        </div>

        <div class="gf-deck-picker">
          <label for="gf-format-select">${t('play.format')}</label>
          <select id="gf-format-select" ${gameFormats === null ? 'disabled' : ''}>
            ${formatOptionsHtml()}
          </select>
        </div>

        ${deckLegalityHtml()}

        <button id="gf-start-btn" type="button" class="primary" ${canStart ? '' : 'disabled'}>
          ${t('goldfish.startBtn')}
        </button>
        ${statusHtml()}
      </div>
    `;
    const select = root.querySelector('#gf-deck-select');
    select?.addEventListener('change', (e) => selectDeck(e.target.value));
    root.querySelector('#gf-refresh-decks')?.addEventListener('click', loadDecks);
    root.querySelector('#gf-format-select')?.addEventListener('change', (e) => {
      selectedFormat = e.target.value;
    });
    root.querySelector('#gf-start-btn')?.addEventListener('click', start);
  }

  // Deck / format `<option>` lists — the favorites-first sort, the loading /
  // error / empty states, and the format fallback are all shared with the
  // Solo and Multiplayer pickers (`gameSetup.js`).
  function deckOptionsHtml() {
    return deckSelectOptionsHtml({
      savedDecks,
      selectedId: selectedDeckId,
      favoriteDeckIds,
      unmodeledDeckIds,
      decksLoading,
      decksLoadError,
      errorText: t('play.serverUnreachableRetry'),
    });
  }

  function formatOptionsHtml() {
    if (gameFormats === null) return `<option>${t('play.loading')}</option>`;
    return formatSelectOptionsHtml(gameFormats, selectedFormat);
  }

  function deckLegalityHtml() {
    if (!selectedDeckId) return '';
    if (validating) return `<p class="server-status pending">${t('play.checkingLegality')}</p>`;
    if (selectedValidation === null) {
      return `<p class="server-status warning">${t('play.legalityUnknown')}</p>`;
    }
    if (selectedValidation.isLegal) {
      return `<p class="server-status ok">${t('play.deckLegal')}</p>`;
    }
    const reasons = (selectedValidation.errors || []).map((e) => `<li>${escapeHtml(e)}</li>`).join('');
    return `
      <div class="server-status warning">${t('play.deckIllegal')}</div>
      ${reasons ? `<ul class="issue-list validation-errors">${reasons}</ul>` : ''}
    `;
  }

  function renderMulligan() {
    const setup = view.setup || { complete: false, mulligan_count: 0, bottom_count: 0 };
    const mulliganCount = setup.mulligan_count;
    const bottomCount = setup.bottom_count;
    const me = view.state.players[0];
    const canKeep = mulliganBottom.size === bottomCount;
    const nextHand = setup.next_hand_size ?? 7;
    root.innerHTML = `
      <div class="goldfish-mulligan">
        <h3>${t('play.openingHand')}</h3>
        <p class="hint">
          ${
            mulliganCount === 0
              ? escapeHtml(t('play.handIntro', { count: me.hand.length }))
              : escapeHtml(mulliganText(setup, mulliganCount, bottomCount, me.hand.length) +
                (bottomCount > 0 ? t('play.pickBottomHint') : ''))
          }
        </p>
        ${statusHtml()}
        <div class="card-grid gf-mulligan-hand">
          ${me.hand.map((o) => mulliganCardHtml(o, bottomCount)).join('')}
        </div>
        <label class="gf-draw-first" title="${escapeHtml(t('goldfish.drawFirstTitle'))}">
          <input type="checkbox" id="gf-draw-first" ${drawFirst ? 'checked' : ''} />
          ${t('goldfish.drawFirstLabel')}
        </label>
        <div class="gf-controls">
          <button id="gf-mulligan-btn" type="button" ${busy ? 'disabled' : ''}>${escapeHtml(t('play.mulliganBtn', { count: nextHand }))}</button>
          <button id="gf-keep-btn" type="button" class="primary" ${busy || !canKeep ? 'disabled' : ''}>
            ${bottomCount === 0 ? t('play.keepHand') : escapeHtml(t('play.keepHandBottom', { picked: mulliganBottom.size, count: bottomCount }))}
          </button>
          <button id="gf-quit-mulligan" type="button" ${busy ? 'disabled' : ''}>${t('play.cancel')}</button>
        </div>
      </div>
    `;
    root.querySelector('#gf-mulligan-btn')?.addEventListener('click', mulligan);
    root.querySelector('#gf-keep-btn')?.addEventListener('click', keepHand);
    root.querySelector('#gf-quit-mulligan')?.addEventListener('click', quit);
    root.querySelector('#gf-draw-first')?.addEventListener('change', (e) => {
      drawFirst = e.target.checked; // client-only until keep_hand commits it
    });
    root.querySelectorAll('[data-bottom-toggle]').forEach((el) => {
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

  // The end-of-match review shown after "Beenden": the final stats digest
  // (kept in `summary` after the session is gone), plus the win/loss banner
  // if the game had actually ended, and a button back to the deck picker.
  function renderSummary() {
    const s = summary.state;
    const me = s ? (s.players.find((p) => !p.is_dummy) || s.players[0]) : null;
    const ended = s && s.game_over;
    const intro = ended
      ? gameResultBanner(s, me)
      : `<p class="hint">${escapeHtml(t('play.gameEndedAfter', { turns: summary.analysis?.turns ?? 0 }))}</p>`;
    root.innerHTML = `
      <div class="goldfish-summary">
        <h3>${t('play.summaryHeading')}</h3>
        ${intro}
        ${analysisHtml(summary.analysis)}
        <div class="gf-controls">
          <button id="gf-summary-new" type="button" class="primary">${t('play.newGame')}</button>
        </div>
      </div>`;
    root.querySelector('#gf-summary-new')?.addEventListener('click', () => {
      summary = null;
      phase = 'pick';
      loadDecks();
      render();
    });
  }

  // The win/loss line for a finished game.
  function gameResultBanner(s, me) {
    const winner = s.winner_id
      ? s.players.find((p) => p.id === s.winner_id)
      : null;
    const youWon = winner && me && winner.id === me.id;
    const banner = winner
      ? youWon
        ? t('goldfish.won')
        : escapeHtml(t('play.lost', { name: winner.name }))
      : t('play.gameOver');
    return `<p class="server-status ${youWon ? 'ok' : 'warning'}">${banner}</p>`;
  }

  function statusHtml() {
    if (!status) return '';
    return `<p class="server-status ${statusKind}">${escapeHtml(status)}</p>`;
  }

  return { mount, onShown };
}
