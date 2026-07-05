// "Goldfisch" tab: play a saved deck against the real backend rules engine
// (mtg_analyzer/game/) via the /api/game session endpoints. Every move
// here is validated server-side and the board shown is the server's
// authoritative GameState. Supports advancing the turn step by step,
// playing/tapping/casting/attacking from the server's legal_actions, and —
// the point of a goldfish — restarting and rewinding at any time (UC3).

import { getState, setState } from './state.js';
import {
  startGoldfish,
  sendGameAction,
  rewindGame,
  restartGame,
  endGame,
  listSavedDecks,
  getDeckValidation,
} from './api.js';
import { preloadCardImages } from './cardImages.js';
import { parseDeckSections } from './parser.js';

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
    await act({ type: 'keep_hand', bottom_instance_ids: Array.from(mulliganBottom) });
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
    sessionId = null;
    view = null;
    phase = 'pick';
    setStatus('', '');
    render();
    if (id) await endGame(id); // best-effort server cleanup
  }

  function applyView(data) {
    sessionId = data.session_id;
    view = data;
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
    const me = s.players[0];
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
    // Attacking swings with every able creature at once (one declaration).
    const allAttackers = actions.filter((a) => a.type === 'attack').map((a) => a.instance_id);
    const stackNonEmpty = s.stack.length > 0;

    root.innerHTML = `
      <div class="goldfish${pending ? ' choosing' : ''}">
        <div class="gf-topbar">
          <div class="gf-turninfo">
            <span class="gf-turn">Zug ${s.turn_number}</span>
            <span class="gf-step">${escapeHtml(labelPhase(s.current_phase))} · ${escapeHtml(labelStep(s.current_step))}</span>
          </div>
          ${manaPoolHtml(me.mana_pool)}
          ${lifeBox('Leben', me.life)}
        </div>

        ${gameOver ? `<p class="server-status warning">Spiel beendet${s.winner_id ? ` – Sieger: ${escapeHtml(s.winner_id)}` : ''}.</p>` : ''}
        ${statusHtml()}
        ${pending ? pendingChoiceHtml(pending) : ''}

        <div class="gf-controls">
          <button id="gf-advance" type="button" class="primary" ${busy || gameOver || pending ? 'disabled' : ''}>Nächster Schritt →</button>
          <button id="gf-autoturn" type="button" ${busy || gameOver || pending ? 'disabled' : ''}>Auto-Zug</button>
          ${stackNonEmpty && !pending ? `<button type="button" data-action='${escapeAttr(JSON.stringify({ type: 'pass_priority' }))}'>Priorität abgeben (Stack auflösen)</button>` : ''}
          ${allAttackers.length && !pending ? `<button type="button" data-action='${escapeAttr(JSON.stringify({ type: 'declare_attackers', instance_ids: allAttackers }))}'>⚔️ Angreifen (${allAttackers.length})</button>` : ''}
          <button id="gf-rewind" type="button" ${busy || !view.can_rewind ? 'disabled' : ''}>↶ Zurücknehmen</button>
          <button id="gf-restart" type="button" ${busy ? 'disabled' : ''}>⟲ Neu starten</button>
          <button id="gf-quit" type="button">Beenden</button>
        </div>

        <div class="gf-zone gf-stack">
          <h4>Stack (${s.stack.length})</h4>
          ${s.stack.length ? `<div class="card-grid">${s.stack.map(stackItemHtml).join('')}</div>` : '<p class="empty-state">leer</p>'}
        </div>

        <div class="gf-zone gf-battlefield">
          <h4>Battlefield (${s.battlefield.length})</h4>
          ${objGrid(s.battlefield, 'Keine Permanents', byInstance, pending)}
        </div>

        <div class="gf-zone-row">
          <div class="gf-zone gf-command">
            <h4>Command Zone</h4>
            ${objGrid(me.command, '–', byInstance, pending)}
          </div>
          <div class="gf-zone gf-graveyard">
            <h4>Friedhof (${me.graveyard.length})</h4>
            ${zoneListHtml(me.graveyard, 'leer')}
          </div>
          <div class="gf-zone gf-exile">
            <h4>Exil (${me.exile.length})</h4>
            ${objGrid(me.exile, 'leer', {}, pending)}
          </div>
          <div class="gf-zone gf-library">
            <h4>Bibliothek</h4>
            <p class="library-count">${me.library_count} Karten</p>
          </div>
        </div>

        <div class="gf-zone gf-hand">
          <h4>Hand (${me.hand.length})</h4>
          ${objGrid(me.hand, 'leer', byInstance, pending)}
        </div>

        ${moveLogHtml(view.move_log)}
      </div>
    `;

    wire();
  }

  function pendingChoiceHtml(pending) {
    if (pending.kind !== 'search') {
      return '<div class="gf-choice"><p class="server-status pending">Entscheidung nötig …</p></div>';
    }
    const label = pending.type_restriction
      ? `Suche in der Bibliothek nach: ${escapeHtml(pending.type_restriction)}`
      : 'Suche in der Bibliothek';
    const options = (pending.eligible || [])
      .map((e) => {
        const action = JSON.stringify({ type: 'choose', instance_id: e.instance_id, name: e.name });
        return `<button type="button" data-hover-card="${escapeHtml(e.name)}" data-action='${escapeAttr(action)}'>${escapeHtml(e.name)}</button>`;
      })
      .join('');
    const decline = pending.optional
      ? `<button type="button" class="gf-decline" data-action='${escapeAttr(JSON.stringify({ type: 'decline' }))}'>Nichts wählen</button>`
      : '';
    return `
      <div class="gf-choice">
        <h4>🔎 ${label}</h4>
        <div class="gf-choice-options">${options}${decline}</div>
      </div>
    `;
  }

  function wire() {
    root.querySelector('#gf-advance')?.addEventListener('click', () => act({ type: 'advance_step' }));
    root.querySelector('#gf-autoturn')?.addEventListener('click', () => act({ type: 'auto_turn' }));
    root.querySelector('#gf-rewind')?.addEventListener('click', rewind);
    root.querySelector('#gf-restart')?.addEventListener('click', restart);
    root.querySelector('#gf-quit')?.addEventListener('click', quit);

    root.querySelectorAll('[data-action]').forEach((el) => {
      el.addEventListener('click', () => {
        act(JSON.parse(el.dataset.action));
      });
    });
  }

  // --- Rendering helpers --------------------------------------------------

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
  // resolved art.
  function stackItemHtml(item) {
    const imageCache = getState().imageCache;
    const obj = item.object;
    const name = obj ? obj.name : item.description || item.kind;
    const image = obj ? imageCache?.get((obj.name || '').toLowerCase()) : null;
    const inner = image?.small
      ? `<img src="${image.small}" alt="${escapeHtml(name)}" loading="lazy" />`
      : escapeHtml(name);
    const classes = ['card'];
    if (image?.small) classes.push('has-image');
    return `
      <div class="gf-card-slot">
        <div class="${classes.join(' ')}" data-hover-card="${escapeHtml(name)}" title="${escapeHtml(name)}">${inner}</div>
      </div>`;
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
    const pt = o.power != null && o.toughness != null ? ` (${o.power}/${o.toughness})` : '';
    const buttons = cardActionButtons(cardActions);
    return `
      <div class="gf-card-slot">
        <div class="${classes.join(' ')}" data-hover-card="${escapeHtml(o.name)}" title="${escapeHtml(o.name)}${pt}${o.tapped ? ' — getappt' : ''}">${inner}</div>
        ${buttons}
      </div>`;
  }

  // The possible actions for a card, rendered as buttons *under* it.
  function cardActionButtons(cardActions) {
    if (!cardActions || !cardActions.length) return '';
    const buttons = [];
    for (const a of cardActions) {
      if (a.type === 'play_land') {
        buttons.push(actionButton({ type: 'play_land', instance_id: a.instance_id, name: a.name }, '🌳 Land spielen'));
      } else if (a.type === 'cast_spell') {
        buttons.push(actionButton({ type: 'cast_spell', instance_id: a.instance_id, name: a.name }, '✨ Zaubern'));
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
      }
      // "attack" is handled by the aggregate button in the controls bar.
    }
    return buttons.length ? `<div class="gf-card-actions">${buttons.join('')}</div>` : '';
  }

  function actionButton(action, label) {
    return `<button type="button" class="gf-card-action" data-action='${escapeAttr(JSON.stringify(action))}'>${label}</button>`;
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
