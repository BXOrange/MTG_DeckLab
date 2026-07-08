// "Goldfisch" tab: play a saved deck against the real backend rules engine
// (mtg_analyzer/game/) via the /api/game session endpoints. Every move
// here is validated server-side and the board shown is the server's
// authoritative GameState. Supports advancing the turn step by step,
// playing/tapping/casting/attacking from the server's legal_actions, and —
// the point of a goldfish — restarting and rewinding at any time (UC3).

import { getState, setState } from './state.js';
import {
  startGoldfish,
  fetchDeckTokens,
  sendGameAction,
  rewindGame,
  restartGame,
  endGame,
  listSavedDecks,
  getDeckValidation,
} from './api.js';
import { preloadCardImages } from './cardImages.js';
import { parseDeckSections } from './parser.js';
import { getCookie, setCookie } from './cookies.js';

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
  // hand) -> 'playing' (the actual board, driven by `view`).
  let phase = 'pick';
  let loadingProgress = { loaded: 0, total: 0 };
  // Cards picked to put on the bottom of the library when keeping a
  // mulliganed hand (London mulligan) — instance ids, cleared whenever a
  // fresh view enters/re-enters the mulligan phase.
  let mulliganBottom = new Set();

  // Battlefield layout: permanents are split across rows by card type
  // (creatures / artifacts+enchantments / lands). Two rows by default; the
  // checkbox promotes lands to their own third row (persisted client-side).
  let threeRows = getCookie('gf_board_rows') === '3';
  // Optional, default-hidden "static effects / layer trace" panel (RULE 613):
  // shows active anthems/grants/type-changes/cost-reductions and how each
  // permanent's characteristics were derived layer by layer. Off by default.
  let showStatics = getCookie('gf_show_statics') === '1';
  // Play-area layout: the static-zone column (command / library / graveyard /
  // exile, stacked) sits on one side, battlefield + hand on the other. Which
  // side the zone column takes is toggleable and persisted.
  let zonesLeft = getCookie('gf_zones_side') === 'left';
  // The stack overlays ("überblendet") the board while non-empty. It can be
  // pushed aside to a compact corner card so priority actions (respond, tap
  // mana) can be taken on the board underneath. Transient (per session).
  let stackAside = false;
  // Attacking creatures whose "choose a defender" submenu is open — only
  // used in the two-step declaration (2+ legal defenders, RULE 508.1a).
  const attackMenuOpen = new Set();
  // A targeting spell (RULE 115) mid-cast: the player has clicked "Zaubern"
  // and is now picking a target per requirement before the cast is sent.
  // `{ instanceId, name, requirements, reqIndex, targets: [], x }` or null.
  // The server offered `requirements` (each with its legal `options`); we
  // walk them in order, collecting one target each, then send the cast.
  let castTargeting = null;
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
  let selectedDeckId = '';
  let selectedValidation = null; // {isLegal, errors, ...} | null
  let validating = false;

  function mount(el) {
    root = el;
    if (!view && savedDecks === null) loadDecks();
    render();
  }

  // Called when the Goldfisch tab is (re)opened — refresh the deck list
  // so newly-saved decks appear, but don't disturb a running game.
  function onShown() {
    if (!view) loadDecks();
  }

  function setStatus(text, kind = '') {
    status = text;
    statusKind = kind;
  }

  // --- Deck picker --------------------------------------------------------

  async function loadDecks() {
    decksLoading = true;
    render();
    const decks = await listSavedDecks();
    decksLoading = false;
    savedDecks = decks || [];
    // Keep a valid selection; validate it if still present.
    if (selectedDeckId && !savedDecks.some((d) => d.id === selectedDeckId)) {
      selectedDeckId = '';
      selectedValidation = null;
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
    const validation = await getDeckValidation(deckId);
    validating = false;
    selectedValidation = validation; // null on failure
    render();
  }

  async function start() {
    if (!selectedDeckId) {
      setStatus('Bitte zuerst ein Deck auswählen.', 'warning');
      render();
      return;
    }
    if (!selectedValidation?.isLegal) {
      setStatus('Nur legale Decks können ein Goldfisch-Spiel starten.', 'warning');
      render();
      return;
    }

    // Preload every card image before the board ever renders, so nothing
    // pops in mid-game — the actual cause of "images not always loaded".
    phase = 'loading';
    loadingProgress = { loaded: 0, total: 0 };
    setStatus('Kartenbilder werden geladen …', 'pending');
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

    await withBusy('Spiel wird gestartet …', async () => {
      const res = await startGoldfish({ deckId: selectedDeckId, shuffle: true });
      if (res.ok) {
        applyView(res.data);
        const notFound = res.data.notFound || [];
        setStatus(
          notFound.length
            ? `Gestartet. Nicht auflösbar: ${notFound.join(', ')}`
            : 'Wähle deine Starthand: behalten oder Mulligan.',
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
  // `merged` (the imageCache), keyed by lowercased token name — the same shape
  // `objCard` reads — so a token GameObject shows its art the instant an effect
  // creates it. Synthesized (inline-P/T) tokens carry no art and are skipped;
  // their board tile keeps the text fallback. Best-effort: a failed fetch just
  // means tokens lazy-load as before.
  async function preloadDeckTokens(merged) {
    const res = await fetchDeckTokens({ deckId: selectedDeckId });
    const tokens = res.ok ? res.data?.tokens || [] : [];
    if (!tokens.length) return;

    for (const t of tokens) {
      const key = (t.name || '').toLowerCase();
      // Don't clobber a real deck card's already-resolved art if a token
      // happens to share its name — the card entry is authoritative.
      if (!key || merged.has(key)) continue;
      merged.set(key, {
        small: t.image_small || null,
        normal: t.image_normal || null,
        card: t,
      });
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

  async function mulligan() {
    await act({ type: 'mulligan' });
  }

  async function keepHand() {
    const setup = view?.setup;
    if (!setup) return;
    if (mulliganBottom.size !== setup.mulligan_count) {
      setStatus(
        `Bitte genau ${setup.mulligan_count} Karte(n) zum Unterlegen auswählen.`,
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
    } else if (mulliganBottom.size < setup.mulligan_count) {
      mulliganBottom.add(instanceId);
    }
    render();
  }

  async function act(action) {
    if (!sessionId) return;
    await withBusy('…', async () => {
      const res = await sendGameAction(sessionId, action);
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

  async function rewind() {
    if (!sessionId) return;
    await withBusy('Zug wird zurückgenommen …', async () => {
      const res = await rewindGame(sessionId, 1);
      if (res.ok) {
        applyView(res.data);
        setStatus('Letzter Zug rückgängig gemacht.', 'ok');
      } else {
        setStatus(`Rückgängig fehlgeschlagen (${res.status}).`, 'warning');
      }
    });
  }

  async function restart() {
    if (!sessionId) return;
    await withBusy('Spiel wird neu gestartet …', async () => {
      const res = await restartGame(sessionId);
      if (res.ok) {
        applyView(res.data);
        setStatus('Spiel neu gestartet.', 'ok');
      } else {
        setStatus(`Neustart fehlgeschlagen (${res.status}).`, 'warning');
      }
    });
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
    // A fresh authoritative state supersedes any half-finished target pick
    // (its options were computed against the previous board).
    castTargeting = null;
    const setupDone = data.setup ? data.setup.complete : true;
    phase = setupDone ? 'playing' : 'mulligan';
    if (!setupDone) mulliganBottom = new Set();
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
    } else if (phase === 'playing' && view) {
      renderGame();
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
        <h3>Spiel wird vorbereitet …</h3>
        <p class="hint">Kartenbilder werden geladen, damit beim Start alles sofort verfügbar ist.</p>
        <div class="gf-loading-bar"><div class="gf-loading-fill" style="width: ${pct}%"></div></div>
        <p class="server-status pending">${total ? `${loaded} / ${total} Bilder geladen …` : 'Lädt …'}</p>
      </div>
    `;
  }

  function renderStartPanel() {
    const legal = selectedValidation?.isLegal === true;
    const canStart = !!selectedDeckId && legal && !busy;
    root.innerHTML = `
      <div class="goldfish-start">
        <h3>Goldfisch-Modus</h3>
        <p class="hint">
          Teste ein gespeichertes Deck ohne Gegner gegen die echten Regeln:
          Schritt für Schritt durch den Zug, Länder spielen, Mana tappen,
          Sprüche wirken – jederzeit mit <strong>Zurücknehmen</strong> und
          <strong>Neu starten</strong>. Nur legale Decks können starten.
        </p>

        <div class="gf-deck-picker">
          <label for="gf-deck-select">Deck</label>
          <select id="gf-deck-select" ${decksLoading ? 'disabled' : ''}>
            ${deckOptionsHtml()}
          </select>
          <button id="gf-refresh-decks" type="button" title="Deckliste neu laden">⟳</button>
        </div>

        ${deckLegalityHtml()}

        <button id="gf-start-btn" type="button" class="primary" ${canStart ? '' : 'disabled'}>
          Goldfisch-Spiel starten
        </button>
        ${statusHtml()}
      </div>
    `;
    const select = root.querySelector('#gf-deck-select');
    select?.addEventListener('change', (e) => selectDeck(e.target.value));
    root.querySelector('#gf-refresh-decks')?.addEventListener('click', loadDecks);
    root.querySelector('#gf-start-btn')?.addEventListener('click', start);
  }

  function deckOptionsHtml() {
    if (decksLoading && savedDecks === null) return '<option>Lädt …</option>';
    if (!savedDecks || !savedDecks.length) {
      return '<option value="">— keine gespeicherten Decks —</option>';
    }
    const options = ['<option value="">— Deck wählen —</option>'];
    for (const d of savedDecks) {
      const name = (d.name || '').trim() || 'Unbenanntes Deck';
      const selected = d.id === selectedDeckId ? ' selected' : '';
      options.push(`<option value="${escapeHtml(d.id)}"${selected}>${escapeHtml(name)}</option>`);
    }
    return options.join('');
  }

  function deckLegalityHtml() {
    if (!selectedDeckId) return '';
    if (validating) return '<p class="server-status pending">Prüfe Legalität …</p>';
    if (selectedValidation === null) {
      return '<p class="server-status warning">Legalität konnte nicht geprüft werden (Server?).</p>';
    }
    if (selectedValidation.isLegal) {
      return '<p class="server-status ok">✅ Deck ist legal.</p>';
    }
    const reasons = (selectedValidation.errors || []).map((e) => `<li>${escapeHtml(e)}</li>`).join('');
    return `
      <div class="server-status warning">🛑 Deck ist nicht legal – Start nicht möglich.</div>
      ${reasons ? `<ul class="issue-list validation-errors">${reasons}</ul>` : ''}
    `;
  }

  function renderMulligan() {
    const setup = view.setup || { complete: false, mulligan_count: 0 };
    const bottomCount = setup.mulligan_count;
    const me = view.state.players[0];
    const canKeep = mulliganBottom.size === bottomCount;
    root.innerHTML = `
      <div class="goldfish-mulligan">
        <h3>Starthand</h3>
        <p class="hint">
          ${
            bottomCount === 0
              ? 'Deine Starthand: 7 Karten. Behalten, oder neu mischen (Mulligan)?'
              : `Mulligan Nr. ${bottomCount}: neue 7 Karten gezogen. Beim Behalten ${bottomCount === 1 ? 'muss 1 Karte' : `müssen ${bottomCount} Karten`} unten in die Bibliothek gelegt werden — wähle sie unten aus.`
          }
        </p>
        ${statusHtml()}
        <div class="card-grid gf-mulligan-hand">
          ${me.hand.map((o) => mulliganCardHtml(o, bottomCount)).join('')}
        </div>
        <label class="gf-draw-first" title="Wer zieht in Zug 1? Standard: du bist am Zug und ziehst nicht (Regel 103.7a).">
          <input type="checkbox" id="gf-draw-first" ${drawFirst ? 'checked' : ''} />
          In Zug 1 eine Karte ziehen (sonst zieht der Goldfisch — du bist am Zug)
        </label>
        <div class="gf-controls">
          <button id="gf-mulligan-btn" type="button" ${busy ? 'disabled' : ''}>🔀 Mulligan (neue 7 ziehen)</button>
          <button id="gf-keep-btn" type="button" class="primary" ${busy || !canKeep ? 'disabled' : ''}>
            ${bottomCount === 0 ? 'Hand behalten' : `Behalten (${mulliganBottom.size}/${bottomCount} unten ausgewählt)`}
          </button>
          <button id="gf-quit-mulligan" type="button" ${busy ? 'disabled' : ''}>Abbrechen</button>
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
    const imageCache = getState().imageCache;
    const image = imageCache?.get((o.name || '').toLowerCase());
    const inner = image?.small
      ? `<img src="${image.small}" alt="${escapeHtml(o.name)}" loading="lazy" />`
      : escapeHtml(o.name);
    const selected = mulliganBottom.has(o.instance_id);
    const classes = ['card'];
    if (image?.small) classes.push('has-image');
    if (bottomCount > 0) classes.push('clickable');
    if (selected) classes.push('selected-bottom');
    const toggleAttr = bottomCount > 0 ? ` data-bottom-toggle="${o.instance_id}"` : '';
    return `
      <div class="gf-card-slot">
        <div class="${classes.join(' ')}" data-hover-card="${escapeHtml(o.name)}" title="${escapeHtml(o.name)}"${toggleAttr}>${inner}</div>
        ${bottomCount > 0 ? `<button type="button" class="gf-card-action" data-bottom-toggle="${o.instance_id}">${selected ? '✓ unten' : 'Nach unten legen'}</button>` : ''}
      </div>`;
  }

  function renderGame() {
    const s = view.state;
    const me = s.players.find((p) => !p.is_dummy) || s.players[0];
    const opp = s.players.find((p) => p.is_dummy) || null;
    const actions = view.legal_actions || [];
    const gameOver = s.game_over;
    const pending = s.pending_choice;

    // Index the per-object actions so each card can show its own buttons
    // directly underneath it (play/cast on hand cards, tap on lands, …).
    const byInstance = {};
    for (const a of actions) {
      if (a.instance_id == null) continue;
      (byInstance[a.instance_id] ||= []).push(a);
    }
    const stackNonEmpty = s.stack.length > 0;
    // A fresh empty stack re-arms the overlay for the next time it fills.
    if (!stackNonEmpty) stackAside = false;

    root.innerHTML = `
      <div class="goldfish${pending || castTargeting ? ' choosing' : ''}">
        <div class="gf-topbar">
          <div class="gf-turninfo">
            <span class="gf-turn">Zug ${s.turn_number}</span>
            <span class="gf-step">${escapeHtml(labelPhase(s.current_phase))} · ${escapeHtml(labelStep(s.current_step))}</span>
          </div>
          ${manaPoolHtml(me.mana_pool)}
          ${lifeBox('Leben', me.life)}
        </div>

        ${opp ? opponentStripHtml(opp) : ''}

        ${gameOver ? gameOverHtml(s, me, opp) : ''}
        ${statusHtml()}
        ${pending ? pendingChoiceHtml(pending) : ''}
        ${castTargeting ? castTargetModalHtml() : ''}

        <div class="gf-controls">
          <button id="gf-advance" type="button" class="primary" ${busy || gameOver || pending ? 'disabled' : ''}>Nächster Schritt →</button>
          <button id="gf-next-decision" type="button" title="Überspringt Schritte ohne Entscheidung und hält bei der nächsten Wahl des aktiven Spielers" ${busy || gameOver || pending ? 'disabled' : ''}>⏭ Nächste Entscheidung</button>
          ${stackNonEmpty && !pending ? `<button type="button" data-action='${escapeAttr(JSON.stringify({ type: 'pass_priority' }))}'>Priorität abgeben (Stack auflösen)</button>` : ''}
          <button id="gf-rewind" type="button" ${busy || !view.can_rewind ? 'disabled' : ''}>↶ Zurücknehmen</button>
          <button id="gf-restart" type="button" ${busy ? 'disabled' : ''}>⟲ Neu starten</button>
          <button id="gf-zones-side" type="button" title="Zonen-Spalte (Bibliothek, Friedhof …) auf die andere Seite legen">⇄ Zonen-Seite</button>
          <button id="gf-quit" type="button">Beenden</button>
        </div>

        <div class="gf-play gf-zones-${zonesLeft ? 'left' : 'right'}">
          <aside class="gf-side">
            <div class="gf-zone gf-command">
              <h4>Command Zone</h4>
              ${objGrid(me.command, '–', byInstance, pending)}
            </div>
            <div class="gf-zone gf-library">
              <h4>Bibliothek</h4>
              <p class="library-count">${me.library_count} Karten</p>
            </div>
            <div class="gf-zone gf-graveyard">
              <h4>Friedhof (${me.graveyard.length})</h4>
              ${zoneListHtml(me.graveyard, 'leer')}
            </div>
            <div class="gf-zone gf-exile">
              <h4>Exil (${me.exile.length})</h4>
              ${objGrid(me.exile, 'leer', {}, pending)}
            </div>
          </aside>

          <div class="gf-main">
            <div class="gf-zone gf-battlefield">
              <div class="gf-bf-head">
                <h4>Battlefield (${s.battlefield.length})</h4>
                <label class="gf-bf-toggle" title="Länder in eine eigene, dritte Reihe legen">
                  <input type="checkbox" id="gf-rows-toggle" ${threeRows ? 'checked' : ''} />
                  Länder in eigener Reihe
                </label>
                <label class="gf-bf-toggle" title="Statische Effekte und die Layer-Herleitung (Regel 613) anzeigen">
                  <input type="checkbox" id="gf-statics-toggle" ${showStatics ? 'checked' : ''} />
                  🔍 Statische Effekte
                </label>
              </div>
              ${battlefieldHtml(s.battlefield, byInstance, pending)}
            </div>

            ${showStatics ? staticEffectsPanelHtml(view, s) : ''}

            <div class="gf-zone gf-hand">
              <h4>Hand (${me.hand.length})</h4>
              ${objGrid(me.hand, 'leer', byInstance, pending)}
            </div>
          </div>

          ${stackNonEmpty && !pending ? stackOverlayHtml(s, stackAside) : ''}
        </div>

        ${moveLogHtml(view.move_log)}
      </div>
    `;

    wire();
  }

  // Icon per choice kind — search, cascade and discover share the same
  // "answer one of these options" shape, so one renderer covers them.
  const CHOICE_ICONS = { search: '🔎', cascade: '🌊', discover: '🔮' };

  function playerName(id) {
    const p = (view.state?.players || []).find((pl) => pl.id === id);
    return p ? p.name : id;
  }

  // A pending choice is rendered as a modal popup for the deciding player:
  // the board behind it is dimmed/locked (`.goldfish.choosing`) so the only
  // thing to do is answer. Each server-provided option becomes one button.
  function pendingChoiceHtml(pending) {
    const icon = CHOICE_ICONS[pending.kind] || '❔';
    const heading = pending.prompt || pending.description || 'Entscheidung nötig';
    // Fall back to eligible cards if an older state has no `options`.
    const options = pending.options
      || (pending.eligible || []).map((e) => ({ id: String(e.instance_id), label: e.name, instance_id: e.instance_id }));

    const buttons = options
      .map((opt) => {
        if (opt.id === 'decline') {
          const action = JSON.stringify({ type: 'decline' });
          return `<button type="button" class="gf-decline" data-action='${escapeAttr(action)}'>${escapeHtml(opt.label || 'Nichts wählen')}</button>`;
        }
        const action = JSON.stringify({ type: 'choose', option_id: opt.id, instance_id: opt.instance_id, name: opt.label });
        const hover = opt.instance_id != null ? ` data-hover-card="${escapeHtml(opt.label || '')}"` : '';
        return `<button type="button"${hover} data-action='${escapeAttr(action)}'>${escapeHtml(opt.label || opt.id)}</button>`;
      })
      .join('');

    return `
      <div class="gf-modal-overlay">
        <div class="gf-modal" role="dialog" aria-modal="true">
          <div class="gf-modal-head">
            <span class="gf-modal-icon">${icon}</span>
            <div>
              <h4>${escapeHtml(heading)}</h4>
              <p class="gf-modal-who">Entscheidung für ${escapeHtml(playerName(pending.player_id))}</p>
            </div>
          </div>
          <div class="gf-choice-options">${buttons}</div>
        </div>
      </div>
    `;
  }

  function wire() {
    root.querySelector('#gf-advance')?.addEventListener('click', () => act({ type: 'advance_step' }));
    root.querySelector('#gf-next-decision')?.addEventListener('click', () => act({ type: 'advance_to_decision' }));
    root.querySelector('#gf-rewind')?.addEventListener('click', rewind);
    root.querySelector('#gf-restart')?.addEventListener('click', restart);
    root.querySelector('#gf-quit')?.addEventListener('click', quit);

    root.querySelectorAll('[data-action]').forEach((el) => {
      el.addEventListener('click', () => {
        act(JSON.parse(el.dataset.action));
      });
    });

    // Battlefield 2-/3-row layout toggle (persisted client-side).
    root.querySelector('#gf-rows-toggle')?.addEventListener('change', (e) => {
      threeRows = e.target.checked;
      setCookie('gf_board_rows', threeRows ? '3' : '2', 365);
      render();
    });

    // Static-effects / layer-trace panel toggle (persisted client-side).
    root.querySelector('#gf-statics-toggle')?.addEventListener('change', (e) => {
      showStatics = e.target.checked;
      setCookie('gf_show_statics', showStatics ? '1' : '0', 365);
      render();
    });

    // Flip the static-zone column (library/graveyard/…) to the other side.
    root.querySelector('#gf-zones-side')?.addEventListener('click', () => {
      zonesLeft = !zonesLeft;
      setCookie('gf_zones_side', zonesLeft ? 'left' : 'right', 365);
      render();
    });

    // Push the stack overlay aside (or bring it back) — a pure client toggle
    // that frees the board underneath for priority responses.
    root.querySelector('[data-stack-aside]')?.addEventListener('click', () => {
      stackAside = !stackAside;
      render();
    });

    // Expand/collapse a creature's "choose a defender" submenu (two-step
    // attack declaration) — a pure client toggle, no server round-trip.
    root.querySelectorAll('[data-attack-toggle]').forEach((el) => {
      el.addEventListener('click', () => {
        const iid = Number(el.dataset.attackToggle);
        if (attackMenuOpen.has(iid)) attackMenuOpen.delete(iid);
        else attackMenuOpen.add(iid);
        render();
      });
    });

    // {X} spells read the announced value from the adjacent number input at
    // click time rather than baking it into a static data-action attribute.
    root.querySelectorAll('[data-cast-x]').forEach((el) => {
      el.addEventListener('click', () => {
        const instanceId = Number(el.dataset.castX);
        const input = root.querySelector(`[data-x-input="${instanceId}"]`);
        const x = Math.max(0, Math.floor(Number(input?.value) || 0));
        act({ type: 'cast_spell', instance_id: instanceId, x });
      });
    });

    // Same, for an {X} in an activated ability's cost.
    root.querySelectorAll('[data-activate-x]').forEach((el) => {
      el.addEventListener('click', () => {
        const { iid, ability_index } = JSON.parse(el.dataset.activateX);
        const input = root.querySelector(`[data-x-input="${iid}"]`);
        const x = Math.max(0, Math.floor(Number(input?.value) || 0));
        act({ type: 'activate_ability', instance_id: iid, ability_index, x });
      });
    });

    // Begin targeting a spell or activated ability: capture its X (if any)
    // now, then open the per-requirement target picker (see `castTargetHtml`).
    root.querySelectorAll('[data-cast-target-start]').forEach((el) => {
      el.addEventListener('click', () => {
        const info = JSON.parse(el.dataset.castTargetStart);
        const iid = Number(info.iid);
        const action = findTargetableAction(iid, info.type, info.ability_index);
        if (!action) return;
        const input = root.querySelector(`[data-x-input="${iid}"]`);
        const x = action.has_x ? Math.max(0, Math.floor(Number(input?.value) || 0)) : 0;
        // The base action the completed targeting will dispatch — a cast or an
        // ability activation, with the same target list appended.
        const send = info.type === 'activate_ability'
          ? { type: 'activate_ability', instance_id: iid, ability_index: info.ability_index, name: action.name }
          : { type: 'cast_spell', instance_id: iid, name: action.name };
        castTargeting = { instanceId: iid, requirements: action.targets || [], reqIndex: 0, targets: [], x, send };
        finishCastIfReady();
      });
    });

    // Record one chosen target (or a skipped optional one) and advance to
    // the next requirement; the cast fires once all are answered.
    root.querySelectorAll('[data-cast-target-pick]').forEach((el) => {
      el.addEventListener('click', () => {
        const { instance_id: iid, target } = JSON.parse(el.dataset.castTargetPick);
        if (!castTargeting || castTargeting.instanceId !== iid) return;
        if (target !== null) castTargeting.targets.push(target);
        castTargeting.reqIndex += 1;
        finishCastIfReady();
      });
    });

    // Abandon a target pick without casting.
    root.querySelectorAll('[data-cast-target-cancel]').forEach((el) => {
      el.addEventListener('click', () => {
        castTargeting = null;
        render();
      });
    });
  }

  // The current view's targetable action for `iid`, so a target pick can read
  // its requirements and {X} flag at click time. Matches cast spells and, by
  // ability index, activated abilities.
  function findTargetableAction(iid, type, abilityIndex) {
    return (view?.legal_actions || []).find(
      (a) =>
        a.type === type &&
        a.instance_id === iid &&
        (type !== 'activate_ability' || a.ability_index === abilityIndex),
    );
  }

  // Fire the cast/activation once every requirement has been answered;
  // otherwise re-render to show the next requirement's targets.
  function finishCastIfReady() {
    if (!castTargeting) return;
    if (castTargeting.reqIndex >= castTargeting.requirements.length) {
      const { send, targets, x } = castTargeting;
      castTargeting = null;
      act({ ...send, targets, x });
    } else {
      render();
    }
  }

  // --- Rendering helpers --------------------------------------------------

  // The battlefield, laid out in rows by card type (creatures / artifacts &
  // enchantments / lands). Attachments (Auras, Equipment — RULE 301/303) are
  // pulled out of the flow and drawn inside a dashed group box around the
  // permanent they're attached to, rather than as loose cards.
  function battlefieldHtml(objs, byInstance = {}, pending = null) {
    if (!objs.length) return '<p class="empty-state">Keine Permanents</p>';
    const imageCache = getState().imageCache;
    const byId = new Map(objs.map((o) => [o.instance_id, o]));

    // Group attachments under their host; anything whose host isn't on the
    // battlefield falls back to rendering as a normal top-level permanent.
    const attachments = new Map(); // host instance_id -> [attached obj]
    const attachedIds = new Set();
    for (const o of objs) {
      if (o.attached_to != null && byId.has(o.attached_to)) {
        if (!attachments.has(o.attached_to)) attachments.set(o.attached_to, []);
        attachments.get(o.attached_to).push(o);
        attachedIds.add(o.instance_id);
      }
    }
    const top = objs.filter((o) => !attachedIds.has(o.instance_id));

    const creatures = top.filter((o) => o.is_creature);
    const lands = top.filter((o) => !o.is_creature && o.is_land);
    const other = top.filter((o) => !o.is_creature && !o.is_land);

    const renderObj = (o) => {
      const actions = pending ? [] : byInstance[o.instance_id] || [];
      const host = objCard(o, imageCache, actions);
      const atts = attachments.get(o.instance_id);
      if (!atts || !atts.length) return host;
      const attached = atts
        .map((a) => objCard(a, imageCache, pending ? [] : byInstance[a.instance_id] || []))
        .join('');
      return `<div class="gf-attach-group" title="Verbundene Karten (Aura/Ausrüstung)">${host}${attached}</div>`;
    };

    const rowHtml = (label, list) =>
      `<div class="gf-bf-row">
        <span class="gf-bf-row-label">${label} (${list.length})</span>
        ${list.length ? `<div class="card-grid">${list.map(renderObj).join('')}</div>` : '<p class="empty-state">–</p>'}
      </div>`;

    const rows = threeRows
      ? [
          rowHtml('Kreaturen', creatures),
          rowHtml('Artefakte & Verzauberungen', other),
          rowHtml('Länder', lands),
        ]
      : [
          rowHtml('Kreaturen', creatures),
          rowHtml('Länder & bleibende Karten', other.concat(lands)),
        ];
    return `<div class="gf-bf-rows">${rows.join('')}</div>`;
  }

  function objGrid(objs, empty, byInstance = {}, pending = null) {
    if (!objs.length) return `<p class="empty-state">${empty}</p>`;
    const imageCache = getState().imageCache;
    return `<div class="card-grid">${objs
      .map((o) => objCard(o, imageCache, pending ? [] : byInstance[o.instance_id] || []))
      .join('')}</div>`;
  }

  // The stack shows card art like the battlefield/hand — a spell reads as
  // itself, not a text description. Abilities with no backing card (no
  // `object`) fall back to their description text, same as a card with no
  // resolved art. Every item is tagged with *what it is* (spell vs.
  // triggered/activated ability) so the stack reads as MTG's stack, not
  // just a row of cards.
  function stackItemHtml(item, index, total) {
    const imageCache = getState().imageCache;
    const obj = item.object;
    const name = obj ? obj.name : item.description || item.kind;
    const image = obj ? imageCache?.get((obj.name || '').toLowerCase()) : null;
    const inner = image?.small
      ? `<img src="${image.small}" alt="${escapeHtml(name)}" loading="lazy" />`
      : escapeHtml(name);
    const classes = ['card'];
    if (image?.small) classes.push('has-image');
    const badge = stackKindBadge(item);
    // The stack resolves LIFO (RULE 608.2): the last-added item is on top
    // and resolves next — flag it so the player sees resolution order.
    const isTop = index === total - 1;
    const order =
      total > 1
        ? `<span class="gf-stack-order">${isTop ? 'oben – löst zuerst auf' : `#${total - index}`}</span>`
        : '';
    return `
      <div class="gf-card-slot gf-stack-item${isTop ? ' is-top' : ''}">
        <span class="gf-stack-badge gf-stack-badge--${badge.cls}">${badge.icon} ${escapeHtml(badge.label)}</span>
        <div class="${classes.join(' ')}" data-hover-card="${escapeHtml(name)}" title="${escapeHtml(name)}">${inner}</div>
        ${order}
      </div>`;
  }

  // The stack rendered as an overlay that "blends over" the play area while it
  // is non-empty. Two modes: full (dims and blocks the board — pass priority
  // to resolve) and pushed *aside* (a compact corner card; the board below is
  // live so you can respond/tap mana during priority, then pass).
  function stackOverlayHtml(s, aside) {
    const cards = s.stack.map((it, i) => stackItemHtml(it, i, s.stack.length)).join('');
    const asideLabel = aside ? '⤢ Stack einblenden' : '⤡ Zur Seite schieben';
    const hint = aside
      ? 'Board aktiv — reagiere und gib dann Priorität ab.'
      : 'Reagieren? Schiebe den Stack zur Seite.';
    return `
      <div class="gf-stack-overlay${aside ? ' aside' : ''}">
        <div class="gf-stack-panel">
          <div class="gf-stack-panel-head">
            <h4>Stack (${s.stack.length})</h4>
            <button type="button" class="gf-stack-aside" data-stack-aside>${asideLabel}</button>
          </div>
          <div class="card-grid gf-stack-grid">${cards}</div>
          <div class="gf-stack-panel-foot">
            <span class="hint">${hint}</span>
            <button type="button" class="primary" data-action='${escapeAttr(JSON.stringify({ type: 'pass_priority' }))}'>Priorität abgeben ▶</button>
          </div>
        </div>
      </div>`;
  }

  // Maps a stack item's category to an icon, a short German label, and a
  // CSS modifier used to colour-code the badge. For spells it refines the
  // label by the card's type line (creature/instant/…), so "Kreatur" and
  // "Spontanzauber" read differently at a glance.
  function stackKindBadge(item) {
    if (item.category === 'triggered_ability') {
      return { cls: 'triggered', icon: '⚡', label: 'Ausgelöste Fähigkeit' };
    }
    if (item.category === 'activated_ability') {
      return { cls: 'activated', icon: '🔧', label: 'Aktivierte Fähigkeit' };
    }
    // A spell: refine by its primary card type.
    return { cls: 'spell', icon: '🃏', label: spellTypeLabel(item.type_line) };
  }

  function spellTypeLabel(typeLine) {
    const t = (typeLine || '').toLowerCase();
    if (t.includes('creature')) return 'Kreaturenzauber';
    if (t.includes('instant')) return 'Spontanzauber';
    if (t.includes('sorcery')) return 'Hexerei';
    if (t.includes('planeswalker')) return 'Planeswalker';
    if (t.includes('artifact')) return 'Artefaktzauber';
    if (t.includes('enchantment')) return 'Verzauberung';
    return 'Zauberspruch';
  }

  // Graveyards pile up fast and are read by name, not recognized by
  // artwork at a glance — a plain list scans faster than a wall of tiny
  // card images (unlike the stack/battlefield, where art helps).
  function zoneListHtml(objs, empty) {
    if (!objs.length) return `<p class="empty-state">${empty}</p>`;
    return `<ul class="gf-zone-list">${objs
      .map((o) => `<li data-hover-card="${escapeHtml(o.name)}">${escapeHtml(o.name)}</li>`)
      .join('')}</ul>`;
  }

  function objCard(o, imageCache, cardActions) {
    const image = imageCache?.get((o.name || '').toLowerCase());
    const inner = image?.small
      ? `<img src="${image.small}" alt="${escapeHtml(o.name)}" loading="lazy" />`
      : escapeHtml(o.name);
    const classes = ['card'];
    if (image?.small) classes.push('has-image');
    if (o.tapped) classes.push('tapped');
    if (o.summoning_sick) classes.push('summoning-sick');
    if (o.attacking) classes.push('attacking');
    const pt = o.power != null && o.toughness != null ? ` (${o.power}/${o.toughness})` : '';
    const buttons = cardActionButtons(cardActions);
    // A creature already declared as an attacker shows who it's swinging at
    // (or a plain ⚔️ for a "bare" solo swing with no defender).
    const attackBadge = o.attacking
      ? `<span class="gf-attacking-badge">⚔️${o.combat_defender ? ` ${escapeHtml(o.combat_defender.label || '')}` : ''}</span>`
      : '';
    // Counters on the permanent (RULE 122), e.g. "+1/+1 ×2" — power/toughness
    // above already reflect their net effect; this shows what's there.
    const counterEntries = Object.entries(o.counters || {});
    const counterBadge = counterEntries.length
      ? `<span class="gf-counter-badge">${counterEntries.map(([k, v]) => `${escapeHtml(k)}×${v}`).join(' · ')}</span>`
      : '';
    // Combat/evasion keywords the engine recognizes (Flying, Trample, …),
    // shown as compact abbreviations with the full names on hover.
    const keywordBadge = (o.keywords && o.keywords.length)
      ? `<span class="gf-keyword-badge" title="${escapeAttr(o.keywords.join(', '))}">${o.keywords.map((k) => escapeHtml(keywordAbbrev(k))).join(' ')}</span>`
      : '';
    return `
      <div class="gf-card-slot">
        <div class="${classes.join(' ')}" data-hover-card="${escapeHtml(o.name)}" title="${escapeHtml(o.name)}${pt}${o.tapped ? ' — getappt' : ''}">${inner}${attackBadge}${counterBadge}${keywordBadge}</div>
        ${buttons}
      </div>`;
  }

  // Short badge label for a combat keyword (the server sends full names like
  // "Flying" / "Protection: R"); the full list is in the badge's tooltip.
  function keywordAbbrev(label) {
    const map = {
      Flying: 'FLY',
      Reach: 'RCH',
      'First Strike': 'FS',
      'Double Strike': 'DS',
      Deathtouch: 'DT',
      Trample: 'TR',
      Vigilance: 'VIG',
      Lifelink: 'LL',
      Menace: 'MEN',
      Defender: 'DEF',
      Haste: 'HST',
      Indestructible: 'IND',
    };
    if (map[label]) return map[label];
    if (label.startsWith('Protection')) return 'PRO';
    return label;
  }

  // The possible actions for a card, rendered as buttons *under* it.
  function cardActionButtons(cardActions) {
    if (!cardActions || !cardActions.length) return '';
    const buttons = [];
    for (const a of cardActions) {
      if (a.type === 'play_land') {
        buttons.push(actionButton({ type: 'play_land', instance_id: a.instance_id, name: a.name }, '🌳 Land spielen'));
      } else if (a.type === 'cast_spell' && a.locked) {
        // RULE 601.2c: the spell needs a target but the board offers none.
        // Show it locked rather than castable so the reason is visible.
        const reason = a.lock_reason || 'Kein gültiges Ziel';
        buttons.push(
          `<button type="button" class="gf-card-action gf-locked" disabled title="${escapeAttr(reason)}">🔒 ${escapeHtml(reason)}</button>`
        );
      } else if (a.type === 'cast_spell' && a.requires_target) {
        // A targeting spell (RULE 115): don't cast on a single click —
        // walk the player through choosing a legal target per requirement
        // first, then send the cast with those targets. Also carries the
        // {X} input when the spell has both a variable cost and a target.
        buttons.push(castTargetHtml(a));
      } else if (a.type === 'cast_spell' && a.has_x) {
        // {X} in the cost (RULE 601.2b): let the player announce a value
        // (capped at what they can currently afford) instead of a plain
        // "Zaubern" button, then send it along with the cast.
        buttons.push(`
          <div class="gf-cast-x">
            <input type="number" min="0" max="${a.max_x}" value="${a.max_x}" data-x-input="${a.instance_id}" />
            <button type="button" class="gf-card-action" data-cast-x="${a.instance_id}">✨ Zaubern (X)</button>
          </div>
        `);
      } else if (a.type === 'cast_spell') {
        // A static cost adjustment (RULE 601.2f) shows as "was → now" on the button.
        const hint = a.base_cost && a.effective_cost && a.base_cost !== a.effective_cost
          ? ` 💰${escapeHtml(a.effective_cost)}`
          : '';
        buttons.push(actionButton({ type: 'cast_spell', instance_id: a.instance_id, name: a.name }, `✨ Zaubern${hint}`));
      } else if (a.type === 'activate_ability' && a.locked) {
        // Needs a target the board can't offer (RULE 602.2b) — show why.
        const reason = a.lock_reason || 'Kein gültiges Ziel';
        buttons.push(
          `<button type="button" class="gf-card-action gf-locked" disabled title="${escapeAttr(reason)}">🔒 ${escapeHtml(reason)}</button>`
        );
      } else if (a.type === 'activate_ability' && a.requires_target) {
        // Targeting activated ability — reuse the spell target picker.
        buttons.push(castTargetHtml(a));
      } else if (a.type === 'activate_ability' && a.has_x) {
        buttons.push(`
          <div class="gf-cast-x">
            <input type="number" min="0" max="${a.max_x}" value="${a.max_x}" data-x-input="${a.instance_id}" />
            <button type="button" class="gf-card-action" data-activate-x='${escapeAttr(JSON.stringify({ iid: a.instance_id, ability_index: a.ability_index }))}'>⚡ ${escapeHtml(a.cost_label || 'Aktivieren')} (X)</button>
          </div>
        `);
      } else if (a.type === 'activate_ability') {
        // A permanent's activated ability (RULE 602), e.g. a fetch land's
        // "{T}, Sacrifice: …". The button shows the cost; effect on the stack.
        buttons.push(
          actionButton(
            { type: 'activate_ability', instance_id: a.instance_id, ability_index: a.ability_index, name: a.name },
            `⚡ ${escapeHtml(a.cost_label || 'Aktivieren')}`
          )
        );
      } else if (a.type === 'tap_for_mana') {
        // One button per production option — the dual-land colour choice.
        const opts = a.options || [{ index: 0, label: '⟳' }];
        for (const opt of opts) {
          const glyph = opt.label || '⟳';
          const text = opts.length > 1 ? `⟳ ${glyph}` : `⟳ Tappen`;
          buttons.push(
            actionButton({ type: 'tap_for_mana', instance_id: a.instance_id, option_index: opt.index }, text)
          );
        }
      } else if (a.type === 'attack') {
        buttons.push(attackControlHtml(a));
      }
    }
    return buttons.length ? `<div class="gf-card-actions">${buttons.join('')}</div>` : '';
  }

  // The target-selection *trigger* shown below a targeting spell/ability in
  // hand — a "Zaubern → Ziel" button that begins targeting (RULE 115). The
  // actual per-requirement target picking happens in a modal pop-up over the
  // board (`castTargetModalHtml`), so a player can't miss the choice.
  function castTargetHtml(a) {
    const iid = a.instance_id;
    // A spell that is both {X} and targeting still needs its X announced;
    // the input travels alongside and is read when targeting begins.
    const xField = a.has_x
      ? `<input type="number" min="0" max="${a.max_x}" value="${a.max_x}" data-x-input="${iid}" />`
      : '';
    const startInfo = JSON.stringify({ iid, type: a.type, ability_index: a.ability_index });
    const label = a.type === 'activate_ability'
      ? `⚡ ${escapeHtml(a.cost_label || 'Aktivieren')} → Ziel ▾`
      : '✨ Zaubern → Ziel ▾';
    return `<div class="gf-cast-targets">${xField}<button type="button" class="gf-card-action" data-cast-target-start='${escapeAttr(startInfo)}'>${label}</button></div>`;
  }

  // The target-picker pop-up: while `castTargeting` is active, the current
  // requirement's legal targets (RULE 115.1) are offered as buttons in a modal
  // over a dimmed board — mirroring the pending-choice modal. Walks one
  // requirement at a time; the last pick sends the cast with all chosen
  // targets. Optional requirements (RULE 115.1a) offer "Kein Ziel".
  function castTargetModalHtml() {
    if (!castTargeting) return '';
    const iid = castTargeting.instanceId;
    const total = castTargeting.requirements.length;
    const idx = castTargeting.reqIndex;
    const req = castTargeting.requirements[idx] || {};
    const options = req.options || [];
    const buttons = options.map((o) => {
      const payload = JSON.stringify({ instance_id: iid, target: targetOptionPayload(o) });
      const hover = o.instance_id != null ? ` data-hover-card="${escapeHtml(o.name || '')}"` : '';
      return `<button type="button"${hover} data-cast-target-pick='${escapeAttr(payload)}'>🎯 ${escapeHtml(o.name)}</button>`;
    });
    if (req.optional) {
      const skip = JSON.stringify({ instance_id: iid, target: null });
      buttons.push(`<button type="button" class="gf-decline" data-cast-target-pick='${escapeAttr(skip)}'>∅ Kein Ziel</button>`);
    }
    const progress = total > 1 ? `Ziel ${idx + 1} von ${total}` : 'Ziel wählen';
    return `
      <div class="gf-modal-overlay">
        <div class="gf-modal gf-target-modal" role="dialog" aria-modal="true">
          <div class="gf-modal-head">
            <span class="gf-modal-icon">🎯</span>
            <div>
              <h4>Ziel wählen: ${escapeHtml(req.label || '')}</h4>
              <p class="gf-modal-who">${escapeHtml(progress)}</p>
            </div>
          </div>
          <div class="gf-choice-options">${buttons.join('')}</div>
          <div class="gf-modal-foot">
            <button type="button" class="gf-decline" data-cast-target-cancel="${iid}">✕ Abbrechen</button>
          </div>
        </div>
      </div>
    `;
  }

  // The wire shape `GameSession._resolve_targets` expects: a player target
  // as `{player_id}`, an object target as `{instance_id}`. The server's
  // option descriptors carry a `name` too, which we drop here.
  function targetOptionPayload(o) {
    return o.player_id != null ? { player_id: o.player_id } : { instance_id: o.instance_id };
  }

  // The attacker-declaration control shown *below* a creature during the
  // declare-attackers step (RULE 508.1a). It's a one- or two-step choice:
  //  • 0 legal defenders (solo goldfish) → one click declares a bare swing.
  //  • exactly 1 → one click declares it, auto-targeting that defender.
  //  • 2+ → click reveals a submenu of defenders below the card (two steps).
  function attackControlHtml(a) {
    const defenders = a.legal_defenders || [];
    const iid = a.instance_id;
    if (defenders.length === 0) {
      return actionButton(
        { type: 'declare_attackers', instance_ids: [iid], name: a.name },
        '⚔️ Angreifen'
      );
    }
    if (defenders.length === 1) {
      const d = defenders[0];
      return actionButton(
        { type: 'declare_attackers', instance_ids: [iid], defender: defenderPayload(d), name: a.name },
        `⚔️ Angreifen → ${escapeHtml(d.label)}`
      );
    }
    const open = attackMenuOpen.has(iid);
    const menu = open
      ? `<div class="gf-attack-defenders">${defenders
          .map((d) =>
            actionButton(
              { type: 'declare_attackers', instance_ids: [iid], defender: defenderPayload(d), name: a.name },
              `→ ${escapeHtml(d.label)}`
            )
          )
          .join('')}</div>`
      : '';
    return `<button type="button" class="gf-card-action" data-attack-toggle="${iid}">⚔️ Angreifen ${open ? '▴' : '▾'}</button>${menu}`;
  }

  // The wire shape the server validates a declared defender against (see
  // `GameEngine.legal_defenders_for` / `GameSession._resolve_defender`).
  function defenderPayload(d) {
    return d.kind === 'planeswalker'
      ? { kind: 'planeswalker', instance_id: d.instance_id }
      : { kind: 'player', id: d.id };
  }

  function actionButton(action, label) {
    return `<button type="button" class="gf-card-action" data-action='${escapeAttr(JSON.stringify(action))}'>${label}</button>`;
  }

  // The passive "goldfish" opponent: a compact strip with its life (the
  // thing you're racing down), plus hidden hand / graveyard / library counts.
  // Its hand is face-down — you're testing your own deck, not reading theirs.
  function opponentStripHtml(opp) {
    return `
      <div class="gf-opponent">
        <span class="gf-opp-name">🐟 ${escapeHtml(opp.name)}</span>
        <span class="gf-opp-life" title="Leben">❤️ ${opp.life}</span>
        ${commanderDamageHtml(opp.commander_damage)}
        <span title="Handkarten (verdeckt)">🖐️ ${opp.hand_count ?? opp.hand?.length ?? 0}</span>
        <span title="Friedhof">⚰️ ${opp.graveyard?.length ?? 0}</span>
        <span title="Bibliothek">📚 ${opp.library_count ?? 0}</span>
        <span class="gf-opp-tag">passiver Gegner</span>
      </div>`;
  }

  // Commander damage taken (RULE 903.10a): one chip per attacking commander,
  // "👑 N/21", turning red as it nears the 21-damage loss threshold.
  function commanderDamageHtml(commanderDamage) {
    const entries = Object.values(commanderDamage || {});
    if (!entries.length) return '';
    return entries
      .map((e) => {
        const lethal = e.amount >= 21 ? ' gf-cmd-dmg--lethal' : '';
        return `<span class="gf-cmd-dmg${lethal}" title="Commander-Schaden von ${escapeHtml(e.name)}">👑 ${e.amount}/21</span>`;
      })
      .join('');
  }

  function gameOverHtml(s, me, opp) {
    return `
      <div class="gf-gameover">
        ${gameResultBanner(s, me)}
        ${analysisHtml(view.analysis)}
      </div>`;
  }

  // The win/loss line for a finished game (shared by the inline game-over
  // block and the "Beenden" summary screen).
  function gameResultBanner(s, me) {
    const winner = s.winner_id
      ? s.players.find((p) => p.id === s.winner_id)
      : null;
    const youWon = winner && me && winner.id === me.id;
    const banner = winner
      ? youWon
        ? '🏆 Gewonnen – der Goldfisch liegt bei 0 Leben.'
        : `Verloren – Sieger: ${escapeHtml(winner.name)}.`
      : 'Spiel beendet.';
    return `<p class="server-status ${youWon ? 'ok' : 'warning'}">${banner}</p>`;
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
      : `<p class="hint">Partie nach ${summary.analysis?.turns ?? 0} Zügen beendet.</p>`;
    root.innerHTML = `
      <div class="goldfish-summary">
        <h3>Partie-Auswertung</h3>
        ${intro}
        ${analysisHtml(summary.analysis)}
        <div class="gf-controls">
          <button id="gf-summary-new" type="button" class="primary">Neues Spiel</button>
        </div>
      </div>`;
    root.querySelector('#gf-summary-new')?.addEventListener('click', () => {
      summary = null;
      phase = 'pick';
      loadDecks();
      render();
    });
  }

  // End-of-game review: totals + a mana-value curve and mana-per-turn bars
  // for each player, side by side, built from the server's stats digest.
  function analysisHtml(analysis) {
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
  function barChartHtml(title, map) {
    const entries = Object.entries(map || {})
      .map(([k, v]) => [Number(k), v])
      .sort((a, b) => a[0] - b[0]);
    if (!entries.length) return `<div class="gf-chart"><span class="gf-chart-title">${title}</span><p class="empty-state">—</p></div>`;
    const max = Math.max(...entries.map(([, v]) => v));
    const bars = entries
      .map(([k, v]) => {
        const h = max ? Math.round((v / max) * 100) : 0;
        return `<div class="gf-bar" title="${k}: ${v}"><span class="gf-bar-v">${v}</span><span class="gf-bar-fill" style="height:${h}%"></span><span class="gf-bar-k">${k}</span></div>`;
      })
      .join('');
    return `<div class="gf-chart"><span class="gf-chart-title">${escapeHtml(title)}</span><div class="gf-bars">${bars}</div></div>`;
  }

  function manaPoolHtml(pool) {
    const order = ['W', 'U', 'B', 'R', 'G', 'C'];
    const glyph = { W: '⚪', U: '🔵', B: '⚫', R: '🔴', G: '🟢', C: '⟡' };
    const parts = order.filter((c) => pool[c] > 0).map((c) => `<span class="gf-mana">${glyph[c]}${pool[c]}</span>`);
    return `<div class="gf-manapool" title="Mana-Pool">${parts.length ? parts.join('') : '<span class="empty-state">kein Mana</span>'}</div>`;
  }

  function moveLogHtml(log) {
    if (!log || !log.length) return '';
    const recent = log.slice(-8);
    return `<div class="gf-movelog"><h4>Verlauf</h4><ol>${recent.map((m) => `<li>${escapeHtml(m)}</li>`).join('')}</ol></div>`;
  }

  // The optional static-effects panel (RULE 613): (1) every active static
  // ability in play and (2) the layer-by-layer derivation of each permanent
  // whose characteristics a static effect changed, so a modified P/T, granted
  // keyword, type change or cost reduction is traceable to its source.
  function staticEffectsPanelHtml(view, s) {
    const actives = view.static_effects || [];
    const traced = (s.battlefield || []).filter((o) => (o.static_trace || []).length);
    const reductions = collectCostReductions(view.legal_actions || []);
    if (!actives.length && !traced.length && !reductions.length) {
      return `<div class="gf-statics"><h4>🔍 Statische Effekte (Layer, Regel 613)</h4>
        <p class="empty-state">Zurzeit keine statischen Effekte im Spiel.</p></div>`;
    }
    const layerLabel = (l) => (l === 'cost' ? 'Kosten (601.2f)' : `Layer ${l}`);
    const activeList = actives.length
      ? `<ul class="gf-static-list">${actives
          .map((e) =>
            `<li><span class="gf-static-layer">${escapeHtml(layerLabel(e.layer))}</span>
             <strong>${escapeHtml(e.source)}</strong> — ${escapeHtml(e.description || '')}
             <span class="gf-static-scope">(${escapeHtml(e.affects)})</span></li>`
          )
          .join('')}</ul>`
      : '<p class="empty-state">Keine aktiven statischen Fähigkeiten.</p>';

    const traceBlocks = traced
      .map((o) => {
        const steps = (o.static_trace || [])
          .map((t) => {
            const pt = t.power != null && t.toughness != null ? ` → ${t.power}/${t.toughness}` : '';
            return `<li><span class="gf-static-layer">L${t.layer}</span>
              ${escapeHtml(t.source)}: ${escapeHtml(t.description)}${escapeHtml(pt)}</li>`;
          })
          .join('');
        const pt = o.power != null && o.toughness != null ? ` — jetzt ${o.power}/${o.toughness}` : '';
        return `<div class="gf-static-trace"><strong>${escapeHtml(o.name)}</strong>${escapeHtml(pt)}
          <ol>${steps}</ol></div>`;
      })
      .join('');

    const costBlock = reductions.length
      ? `<div class="gf-static-costs"><h5>Kostenanpassungen</h5><ul class="gf-static-list">${reductions
          .map((r) => `<li><strong>${escapeHtml(r.name)}</strong>: ${escapeHtml(r.base)} → ${escapeHtml(r.effective)}</li>`)
          .join('')}</ul></div>`
      : '';

    return `
      <div class="gf-statics">
        <h4>🔍 Statische Effekte (Layer, Regel 613)</h4>
        <div class="gf-static-active"><h5>Aktive statische Fähigkeiten</h5>${activeList}</div>
        ${traceBlocks ? `<div class="gf-static-traces"><h5>Layer-Herleitung</h5>${traceBlocks}</div>` : ''}
        ${costBlock}
      </div>`;
  }

  // Castable spells whose cost a static effect changed (base vs. effective).
  function collectCostReductions(actions) {
    return actions
      .filter((a) => a.type === 'cast_spell' && a.base_cost && a.effective_cost && a.base_cost !== a.effective_cost)
      .map((a) => ({ name: a.name, base: a.base_cost, effective: a.effective_cost }));
  }

  function statusHtml() {
    if (!status) return '';
    return `<p class="server-status ${statusKind}">${escapeHtml(status)}</p>`;
  }

  return { mount, onShown };
}

const PHASE_LABELS = {
  beginning: 'Anfang',
  precombat_main: 'Hauptphase I',
  combat: 'Kampf',
  postcombat_main: 'Hauptphase II',
  ending: 'Endphase',
};
const STEP_LABELS = {
  untap: 'Enttappen',
  upkeep: 'Versorgung',
  draw: 'Ziehen',
  main1: 'Hauptphase I',
  begin_combat: 'Kampfbeginn',
  declare_attackers: 'Angreifer',
  declare_blockers: 'Blocker',
  combat_damage: 'Kampfschaden',
  end_combat: 'Kampfende',
  main2: 'Hauptphase II',
  end: 'Ende',
  cleanup: 'Aufräumen',
};

function labelPhase(name) {
  return PHASE_LABELS[name] || name || '—';
}
function labelStep(name) {
  return STEP_LABELS[name] || name || '—';
}

function lifeBox(label, life) {
  return `<div class="gf-life"><span class="gf-life-label">${escapeHtml(label)}</span><span class="life-total">${life}</span></div>`;
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str == null ? '' : String(str);
  return div.innerHTML;
}

function escapeAttr(str) {
  return String(str).replace(/'/g, '&#39;').replace(/"/g, '&quot;');
}
