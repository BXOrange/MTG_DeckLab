// "Replay" tab (a.k.a. Puzzle mode): build an arbitrary board state and
// play it against the real backend rules engine (mtg_analyzer/game/). Unlike
// Goldfisch it does not deal a deck from turn 1 — you add/remove cards and
// tokens to any zone, tap/flip them, set counters, set life/poison/etc, and
// save/load the whole thing as a JSON file. Editing goes through the server's
// `edit_*` session actions (snapshotted, so Rückgängig works on edits too).

import {
  startReplay,
  exportReplay,
  sendGameAction,
  rewindGame,
  endGame,
  resolveCards,
  listCachedCards,
  cardImageUrl,
  listTokenImages,
  tokenImageUrl,
} from './api.js';
import { getPlayerName } from './settings.js';
import { getCookie, setCookie } from './cookies.js';
import { createGameBoardView } from './gameBoardView.js';
import { t } from './i18n.js';

// Steps of a default turn (mirrors backend game/phases.py), for the
// "Zug/Phase" control that positions the engine mid-turn.
const STEPS = [
  ['untap', t('bd.step.untap')],
  ['upkeep', t('bd.step.upkeep')],
  ['draw', t('bd.step.draw')],
  ['main1', t('bd.step.main1')],
  ['begin_combat', t('bd.step.begin_combat')],
  ['declare_attackers', t('bd.step.declare_attackers')],
  ['declare_blockers', t('bd.step.declare_blockers')],
  ['combat_damage', t('bd.step.combat_damage')],
  ['end_combat', t('bd.step.end_combat')],
  ['main2', t('bd.step.main2')],
  ['end', t('bd.step.end')],
  ['cleanup', t('bd.step.cleanup')],
];

// Zones, in editor display order (battlefield is the shared field; the rest
// are the player's personal zones). value → German label.
const ZONES = [
  ['battlefield', t('rp.zone.battlefield')],
  ['hand', t('rp.zone.hand')],
  ['graveyard', t('rp.zone.graveyard')],
  ['library', t('rp.zone.library')],
  ['exile', t('rp.zone.exile')],
  ['command', t('rp.zone.command')],
];

const COLORS = [['W', 'W'], ['U', 'U'], ['B', 'B'], ['R', 'R'], ['G', 'G']];

// A curated set of common token types (add-token modal): clicking one fills
// the manual form below rather than adding immediately, so it's still a
// starting point to tweak, not a second, less-flexible path. `oracle_text`
// (when set) is real oracle text — the engine's keyword recognition
// (combat.js) reads it off the token like any other card, so e.g. "Flying"
// here actually grants the keyword, not just a label.
const TOKEN_PRESETS = [
  { name: 'Soldier', type_line: 'Creature — Soldier', power: 1, toughness: 1, colors: ['W'] },
  { name: 'Spirit', type_line: 'Creature — Spirit', power: 1, toughness: 1, colors: ['W'], oracle_text: 'Flying' },
  { name: 'Angel', type_line: 'Creature — Angel', power: 4, toughness: 4, colors: ['W'], oracle_text: 'Flying, vigilance' },
  { name: 'Bird', type_line: 'Creature — Bird', power: 1, toughness: 1, colors: ['U'], oracle_text: 'Flying' },
  { name: 'Zombie', type_line: 'Creature — Zombie', power: 2, toughness: 2, colors: ['B'] },
  { name: 'Goblin', type_line: 'Creature — Goblin', power: 1, toughness: 1, colors: ['R'] },
  { name: 'Dragon', type_line: 'Creature — Dragon', power: 5, toughness: 5, colors: ['R'], oracle_text: 'Flying' },
  { name: 'Elf Warrior', type_line: 'Creature — Elf Warrior', power: 1, toughness: 1, colors: ['G'] },
  { name: 'Saproling', type_line: 'Creature — Saproling', power: 1, toughness: 1, colors: ['G'] },
  { name: 'Beast', type_line: 'Creature — Beast', power: 3, toughness: 3, colors: ['G'] },
  { name: 'Wolf', type_line: 'Creature — Wolf', power: 2, toughness: 2, colors: ['G'] },
  {
    name: 'Treasure',
    type_line: 'Artifact — Treasure',
    power: null,
    toughness: null,
    colors: [],
    oracle_text: '{T}, Sacrifice this artifact: Add one mana of any color.',
  },
  {
    name: 'Clue',
    type_line: 'Artifact — Clue',
    power: null,
    toughness: null,
    colors: [],
    oracle_text: '{2}, Sacrifice this artifact: Draw a card.',
  },
  {
    name: 'Food',
    type_line: 'Artifact — Food',
    power: null,
    toughness: null,
    colors: [],
    oracle_text: '{2}, {T}, Sacrifice this artifact: You gain 3 life.',
  },
];

// Mana pool editor rows (RULE 106) — same order/glyphs as the Goldfisch
// board's read-only display (gameBoardView.js's `manaPoolHtml`).
const MANA_TYPES = [
  ['W', '⚪'],
  ['U', '🔵'],
  ['B', '⚫'],
  ['R', '🔴'],
  ['G', '🟢'],
  ['C', '⟡'],
];

export function createReplayView() {
  let sessionId = null;
  let view = null; // last server session view
  let status = '';
  let statusKind = '';
  let busy = false;
  let root = null;

  // A modal overlay for adding a card (search) or a token (form). Shape:
  // { kind: 'card'|'token', playerId, zone, query, results } | null.
  let modal = null;

  // instance_id of the card currently being drag&dropped between zones, or
  // null — see `wireZoneDropTarget`.
  let draggedIid = null;

  // The locally cached card pool (GET /api/cards, all previously-resolved
  // cards) for the add-card modal's live substring search — loaded once per
  // modal open, then filtered client-side on every keystroke (no server
  // round trip per keystroke), same pattern as the card-cache tab
  // (cachedCardsView.js's `allCards`). null until loaded.
  let cardPool = null;

  // Board layout — mirrors the Goldfisch board (goldfishView.js) so the two
  // modes read as the same game board: creatures/lands split across battlefield
  // rows (optionally a third row for lands), and the static-zone column
  // (command/library/graveyard/exile) can sit on either side. Persisted
  // client-side like their Goldfisch counterparts, but under separate cookie
  // keys so the two tabs' layouts don't fight each other.
  let threeRows = getCookie('replay_board_rows') === '3';
  let zonesLeft = getCookie('replay_zones_side') === 'left';

  // 'edit' (Konfigurations-Modus, the board editor below) or 'play'
  // (Spielmodus — the shared interactive board, `board`). Only in 'play'
  // does the turn engine actually run (advance_step/cast/attack/…); 'edit'
  // is pure state mutation via `edit_*` actions. Same session throughout —
  // switching modes is a client-side view change, not a new/ended session.
  let mode = 'edit';
  const board = createGameBoardView({
    onViewChange: (v) => {
      view = v;
    },
    extraControls: () => [
      {
        id: 'to-editor',
        label: t('rp.backToEditor'),
        title: t('rp.backToEditorTitle'),
        onClick: () => {
          mode = 'edit';
          render();
        },
      },
    ],
  });

  function enterPlayMode() {
    mode = 'play';
    board.start(sessionId, view);
    loadPlayerAssets();
  }

  // The local player's custom token art (Einstellungen tab) — a puzzle
  // board has no single "deck" to read a sleeve selection from, so only
  // token images are wired up here (see gameBoardView.js resolveImageUrl).
  // Best-effort: a failed fetch just falls back to the default rendering.
  async function loadPlayerAssets() {
    const playerName = getPlayerName();
    if (!playerName) return;
    const images = await listTokenImages(playerName);
    const tokenImages = {};
    for (const t of images || []) {
      tokenImages[(t.token_name || '').toLowerCase()] = tokenImageUrl(playerName, t.token_name);
    }
    board.setAssets({ tokenImages });
  }

  function mount(el) {
    root = el;
    board.mount(el);
    render();
  }

  function onShown() {
    render();
  }

  function setStatus(text, kind = '') {
    status = text;
    statusKind = kind;
  }

  async function withBusy(fn) {
    busy = true;
    render();
    try {
      await fn();
    } finally {
      busy = false;
      render();
    }
  }

  function applyView(data) {
    view = data;
    sessionId = data?.session_id ?? sessionId;
  }

  // --- Session lifecycle --------------------------------------------------

  async function startBlank(numPlayers) {
    await withBusy(async () => {
      const res = await startReplay(null, numPlayers);
      if (res.ok) {
        applyView(res.data);
        setStatus(t('rp.saveCreated'), 'ok');
      } else {
        setStatus(`Konnte nicht starten (${res.status}).`, 'warning');
      }
    });
  }

  async function loadFromDescriptor(descriptor) {
    await withBusy(async () => {
      const res = await startReplay(descriptor, 1);
      if (res.ok) {
        applyView(res.data);
        setStatus(t('rp.saveLoaded'), 'ok');
      } else {
        setStatus(`Laden fehlgeschlagen (${res.status}).`, 'warning');
      }
    });
  }

  function importFile(file) {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const descriptor = JSON.parse(String(reader.result));
        if (descriptor?.format !== 'mtg-replay') {
          setStatus(t('rp.invalidFile'), 'warning');
          render();
          return;
        }
        loadFromDescriptor(descriptor);
      } catch {
        setStatus(t('rp.fileReadFailed'), 'warning');
        render();
      }
    };
    reader.readAsText(file);
  }

  async function exportToFile() {
    if (!sessionId) return;
    const res = await exportReplay(sessionId);
    if (!res.ok || !res.data) {
      setStatus(`Export fehlgeschlagen (${res.status}).`, 'warning');
      render();
      return;
    }
    downloadJson(res.data, 'replay.json');
    setStatus(t('rp.exported'), 'ok');
    render();
  }

  async function quit() {
    const id = sessionId;
    sessionId = null;
    view = null;
    modal = null;
    setStatus('', '');
    render();
    if (id) await endGame(id);
  }

  async function act(action) {
    if (!sessionId) return;
    await withBusy(async () => {
      const res = await sendGameAction(sessionId, action);
      if (res.ok) {
        applyView(res.data);
        setStatus('', '');
      } else if (res.status === 400) {
        setStatus(`Aktion nicht erlaubt: ${res.data?.detail ?? ''}`, 'warning');
      } else if (res.status === 404) {
        setStatus(t('rp.sessionExpired'), 'warning');
        sessionId = null;
        view = null;
      } else {
        setStatus(`Fehler (${res.status}).`, 'warning');
      }
    });
  }

  async function rewind() {
    if (!sessionId) return;
    await withBusy(async () => {
      const res = await rewindGame(sessionId, 1);
      if (res.ok) applyView(res.data);
      else setStatus(t('rp.undoFailed', { status: res.status }), 'warning');
    });
  }

  // --- Add-card / add-token modal ----------------------------------------

  // Loads the local card pool once (if not already cached) for the modal's
  // live substring search, then re-renders so results appear as soon as it
  // arrives.
  async function ensureCardPool() {
    if (cardPool != null) return;
    const cards = await listCachedCards();
    // VIS-1: keep `cardPool` null on a network failure (rather than
    // collapsing it to `[]`) so the next modal open retries instead of
    // silently reading as "Kartenpool geladen, 0 Treffer" forever.
    cardPool = cards;
    if (modal?.kind === 'card') {
      updateLiveResults();
      render();
    }
  }

  // Substring match on name (case-insensitive, e.g. "Elv" -> "Llanowar
  // Elves"/"Elvish Mystic") against the already-cached pool — instant,
  // no server round trip. Matches at the start of the name sort first.
  function filterCardPool(query) {
    const q = query.trim().toLowerCase();
    if (!q || !cardPool) return [];
    return cardPool
      .filter((c) => (c.name || '').toLowerCase().includes(q))
      .sort((a, b) => {
        const an = a.name.toLowerCase().startsWith(q) ? 0 : 1;
        const bn = b.name.toLowerCase().startsWith(q) ? 0 : 1;
        return an - bn || a.name.localeCompare(b.name);
      })
      .slice(0, 40);
  }

  // Gate: no live search until there's enough of a name to narrow down —
  // below this, every card matches "e" or "a" and the list is just noise.
  const MIN_SEARCH_CHARS = 3;

  function updateLiveResults() {
    if (!modal) return;
    const query = (modal.query || '').trim();
    if (!query) {
      modal.results = [];
      modal.searched = false;
      modal.tooShort = false;
      return;
    }
    if (query.length < MIN_SEARCH_CHARS) {
      modal.results = [];
      modal.searched = true;
      modal.tooShort = true;
      return;
    }
    modal.results = filterCardPool(query);
    modal.searched = true;
    modal.tooShort = false;
  }

  // Fallback for a card not yet in the local pool: resolves (and fetches
  // from Scryfall on first use) by exact name via the backend's lazy cache,
  // same as before — the live substring search above only ever matches
  // what's already cached.
  async function searchCard() {
    if (!modal) return;
    const query = (modal.query || '').trim();
    if (!query) return;
    busy = true;
    render();
    const result = await resolveCards([query]);
    busy = false;
    const cards = result?.cards ? Object.values(result.cards) : [];
    modal.results = cards;
    modal.searched = true;
    render();
  }

  async function addResolvedCard(card) {
    if (!modal) return;
    const { playerId, zone } = modal;
    modal = null;
    await act({
      type: 'edit_add_object',
      zone,
      owner_id: playerId,
      controller_id: playerId,
      name: card.name,
      card_id: card.id,
    });
  }

  async function addToken(token) {
    if (!modal) return;
    const { playerId, zone } = modal;
    modal = null;
    await act({
      type: 'edit_add_object',
      zone,
      owner_id: playerId,
      controller_id: playerId,
      token,
    });
  }

  // --- Rendering ----------------------------------------------------------

  function render() {
    if (!root) return;
    if (!view) {
      mode = 'edit';
      renderStart();
    } else if (mode === 'play') {
      // The shared board (`board`) repaints itself on every action; nothing
      // to do here beyond having called `board.start()` in `enterPlayMode()`.
    } else {
      renderEditor();
    }
    if (modal) renderModal();
  }

  function renderStart() {
    root.innerHTML = `
      <div class="replay-start">
        <h2>${t('rp.title')}</h2>
        <p>${t('rp.intro')}</p>
        <div class="replay-start-actions">
          <button type="button" class="primary" data-start="1">${t('rp.newPuzzle1')}</button>
          <button type="button" data-start="2">${t('rp.withOpponent')}</button>
          <button type="button" data-start="3">${t('rp.with2Opponents')}</button>
          <button type="button" data-start="4">${t('rp.with3Opponents')}</button>
          <label class="replay-import-label">Importieren…
            <input type="file" accept="application/json,.json" id="replay-import" hidden />
          </label>
        </div>
        ${statusLine()}
      </div>`;
    root.querySelectorAll('[data-start]').forEach((el) =>
      el.addEventListener('click', () => startBlank(Number(el.dataset.start))),
    );
    root.querySelector('#replay-import')?.addEventListener('change', (e) =>
      importFile(e.target.files?.[0]),
    );
  }

  // 1 player stacks single-column; 2 goes side-by-side (`.two`); 3-4 tile
  // into the same clockwise 2x2 pod grid Multiplayer's board uses
  // (`gameBoardView.js`'s `.gf-pod-grid` — see the mirrored `.pod` CSS rules
  // next to `.replay-players` in main.css) so a 3-4 player puzzle lays out
  // the same way a real table of that size does.
  function replayPlayersClass(count) {
    if (count >= 3) return ' pod';
    if (count > 1) return ' two';
    return '';
  }

  function renderEditor() {
    const s = view.state;
    root.innerHTML = `
      <div class="replay-editor">
        ${renderToolbar(s)}
        ${statusLine()}
        <div class="replay-players${replayPlayersClass(s.players.length)}">
          ${s.players.map((p) => renderPlayer(p, s)).join('')}
        </div>
      </div>`;
    wireEditor();
  }

  function renderToolbar(s) {
    const players = s.players;
    const stepOptions = STEPS.map(
      ([v, l]) => `<option value="${v}"${v === s.current_step ? ' selected' : ''}>${escapeHtml(l)}</option>`,
    ).join('');
    const activeOptions = players
      .map((p) => `<option value="${escapeAttr(p.id)}"${p.id === s.active_player_id ? ' selected' : ''}>${escapeHtml(p.name)}</option>`)
      .join('');
    return `
      <div class="replay-toolbar">
        <div class="replay-toolbar-group">
          <button type="button" data-tool="new">${t('rp.tool.new')}</button>
          <label class="replay-import-label">Importieren
            <input type="file" accept="application/json,.json" id="replay-import" hidden />
          </label>
          <button type="button" data-tool="export">${t('rp.tool.export')}</button>
          <button type="button" data-tool="quit">${t('rp.tool.quit')}</button>
        </div>
        <div class="replay-toolbar-group">
          <span>${t('rp.turn')} ${s.turn_nr}</span>
          <label>${t('rp.playerTurn')} <input type="number" min="1" value="${s.internal_turn.number}" id="replay-turn" /></label>
          <label>${t('rp.step')} <select id="replay-step">${stepOptions}</select></label>
          <label>${t('rp.active')} <select id="replay-active">${activeOptions}</select></label>
        </div>
        <div class="replay-toolbar-group">
          <button type="button" data-tool="rewind" ${view.can_rewind ? '' : 'disabled'}>${t('rp.tool.rewind')}</button>
          <button type="button" data-tool="zones-side" title="${escapeAttr(t('rp.tool.zonesSideTitle'))}">${t('rp.tool.zonesSide')}</button>
        </div>
        <div class="replay-toolbar-group">
          <button type="button" class="primary" data-tool="play-mode" title="${escapeAttr(t('rp.tool.playModeTitle'))}">${t('rp.tool.playMode')}</button>
        </div>
      </div>`;
  }

  // A compact editable mana pool (RULE 106) — one small number input per
  // color, matching the Goldfisch board's read-only glyphs.
  function manaPoolEditorHtml(p) {
    const pool = p.mana_pool || {};
    return `
      <div class="replay-manapool">
        <span class="replay-manapool-label">${t('rp.manaPool')}</span>
        ${MANA_TYPES.map(
          ([type, glyph]) => `
          <label class="replay-mana-input" title="${escapeAttr(type)}-Mana">
            ${glyph}<input type="number" min="0" class="replay-mana" data-mana-type="${type}" value="${pool[type] ?? 0}" />
          </label>`,
        ).join('')}
      </div>`;
  }

  function renderPlayer(p, s) {
    const bf = s.battlefield.filter((o) => o.controller_id === p.id);
    const counters = Object.entries(p.counters || {});
    const cmdDmg = Object.entries(p.commander_damage || {});
    return `
      <section class="replay-player" data-player="${escapeAttr(p.id)}">
        <header class="replay-player-head">
          <h3>${escapeHtml(p.name)}</h3>
          <label>${t('rp.life')} <input type="number" class="replay-life" value="${p.life}" /></label>
          <label>${t('rp.poison')} <input type="number" min="0" class="replay-poison" value="${p.poison ?? 0}" /></label>
          <label>${t('rp.energy')} <input type="number" min="0" class="replay-pcounter" data-counter="energy" value="${(p.counters || {}).energy ?? 0}" /></label>
          <label>${t('rp.experience')} <input type="number" min="0" class="replay-pcounter" data-counter="experience" value="${(p.counters || {}).experience ?? 0}" /></label>
          <button type="button" class="replay-pcounter-add" title="${escapeAttr(t('rp.addCounterTitle'))}">${t('rp.addCounter')}</button>
        </header>
        ${manaPoolEditorHtml(p)}
        ${counters.filter(([k]) => k !== 'energy' && k !== 'experience').length
          ? `<div class="replay-extra-counters">${counters
              .filter(([k]) => k !== 'energy' && k !== 'experience')
              .map(([k, v]) => `<span class="replay-chip">${escapeHtml(k)}: ${v}</span>`)
              .join('')}</div>`
          : ''}
        ${cmdDmg.length
          ? `<div class="replay-extra-counters">${cmdDmg
              .map(([, d]) => `<span class="replay-chip">⚔️ ${escapeHtml(d.name || '')}: ${d.amount}</span>`)
              .join('')}</div>`
          : ''}
        <div class="gf-play gf-zones-${zonesLeft ? 'left' : 'right'}">
          <aside class="gf-side">
            ${renderZone(p, 'command', t('rp.zone.command'), p.command || [], s, 'gf-command')}
            ${renderLibraryZone(p, p.library || [], s)}
            ${renderZone(p, 'graveyard', t('rp.zone.graveyard'), p.graveyard || [], s, 'gf-graveyard')}
            ${renderZone(p, 'exile', t('rp.zone.exile'), p.exile || [], s, 'gf-exile')}
          </aside>
          <div class="gf-main">
            ${renderBattlefieldZone(p, bf, s)}
            ${renderZone(p, 'hand', t('rp.zone.hand'), p.hand || [], s, 'gf-hand')}
          </div>
        </div>
      </section>`;
  }

  // A personal zone box — same `gf-zone` shell as the Goldfisch board, plus
  // the editor's "+ Karte" header control those zones don't need. No "+
  // Token": a token ceases to exist off the battlefield (RULE 111.7), so
  // only `renderBattlefieldZone` offers one.
  function renderZone(p, zone, label, objs, s, extraClass = '') {
    return `
      <div class="gf-zone replay-zone${extraClass ? ` ${extraClass}` : ''}" data-zone="${zone}" data-player="${escapeAttr(p.id)}">
        <div class="replay-zone-head">
          <span>${escapeHtml(label)} <span class="replay-count">${objs.length}</span></span>
          <span class="replay-zone-add">
            <button type="button" class="replay-add-card" title="${escapeAttr(t('rp.addCardTitle'))}">${t('rp.addCard')}</button>
          </span>
        </div>
        <div class="replay-zone-cards">
          ${objs.map((o) => renderCard(o, p, s)).join('') || `<span class="empty-state">${t('rp.empty')}</span>`}
        </div>
      </div>`;
  }

  // The library zone box: just a count + "Anzeigen" button — the list
  // itself opens in a popup (`renderLibraryModal`), not inline. A deck can
  // run to 40+ cards; inline-expanding it in the sidebar column blew out
  // that column's height and broke the board layout, so it's an overlay
  // instead (same idea as the Goldfisch board's stack overlay), hidden
  // until opened, closed again after.
  function renderLibraryZone(p, lib, s) {
    return `
      <div class="gf-zone replay-zone gf-library" data-zone="library" data-player="${escapeAttr(p.id)}">
        <div class="replay-zone-head">
          <span>${t('rp.libraryLabel')} <span class="replay-count">${lib.length}</span></span>
          <span class="replay-zone-add">
            <button type="button" class="replay-lib-open" title="${escapeAttr(t('rp.libOpenTitle'))}">${t('rp.libOpen')}</button>
            <button type="button" class="replay-add-card" title="${escapeAttr(t('rp.addCardTitle'))}">${t('rp.addCard')}</button>
          </span>
        </div>
      </div>`;
  }

  // The library's contents, shown in a modal pop-up (`modal.kind === 'library'`)
  // rather than inline — see `renderLibraryZone`.
  function renderLibraryModal() {
    const s = view.state;
    const player = s.players.find((pl) => pl.id === modal.playerId);
    const lib = player ? player.library || [] : [];
    return `
      <div class="replay-modal replay-library-modal">
        <div class="replay-modal-head">
          <h3>Bibliothek${player ? ` — ${escapeHtml(player.name)}` : ''} (${lib.length})</h3>
          <button type="button" data-modal-close>✕</button>
        </div>
        <div class="replay-modal-body">${renderLibraryList(lib, s)}</div>
      </div>`;
  }

  function renderLibraryList(lib, s) {
    if (!lib.length) return '<p class="empty-state">leer</p>';
    // Displayed top-of-library first; storage is bottom-first (the *end* of
    // the array is the top of the deck — see `Player.library`).
    const topFirst = [...lib].reverse();
    const moveOptions = moveOptionsHtml(s);
    const items = topFirst
      .map((o, i) => {
        const isTop = i === 0;
        const isBottom = i === topFirst.length - 1;
        const pos = isTop ? 'oben' : isBottom ? 'unten' : String(i + 1);
        return `
          <li class="replay-lib-item" data-iid="${o.instance_id}" data-hover-card="${escapeHtml(o.name)}" title="${escapeHtml(o.name)}">
            <span class="replay-lib-pos">${pos}</span>
            <span class="replay-lib-name">${escapeHtml(o.name)}</span>
            <span class="replay-lib-tools">
              <button type="button" data-lib-act="up" title="${escapeAttr(t('rp.libUpTitle'))}" ${isTop ? 'disabled' : ''}>▲</button>
              <button type="button" data-lib-act="down" title="${escapeAttr(t('rp.libDownTitle'))}" ${isBottom ? 'disabled' : ''}>▼</button>
              <select class="replay-move" title="${escapeAttr(t('rp.moveTitle'))}"><option value="">${t('rp.moveToZone')}</option>${moveOptions}</select>
              <button type="button" data-lib-act="remove" title="${escapeAttr(t('rp.removeTitle'))}">✕</button>
            </span>
          </li>`;
      })
      .join('');
    return `<ol class="replay-lib-list">${items}</ol>`;
  }

  // The battlefield zone: same row-by-type grouping (creatures / artifacts &
  // enchantments / lands, or two rows) and attachment framing as the
  // Goldfisch board (`battlefieldHtml` in goldfishView.js), plus the editor's
  // add-card/add-token controls and the row-count toggle.
  function renderBattlefieldZone(p, bf, s) {
    return `
      <div class="gf-zone replay-zone gf-battlefield" data-zone="battlefield" data-player="${escapeAttr(p.id)}">
        <div class="gf-bf-head">
          <span>${t('rp.battlefieldLabel')} <span class="replay-count">${bf.length}</span></span>
          <label class="gf-bf-toggle" title="${escapeAttr(t('bd.bf.landsOwnRowTitle'))}">
            <input type="checkbox" class="replay-rows-toggle" ${threeRows ? 'checked' : ''} />
            ${t('bd.bf.landsOwnRow')}
          </label>
          <span class="replay-zone-add">
            <button type="button" class="replay-add-card" title="${escapeAttr(t('rp.addCardTitle'))}">${t('rp.addCard')}</button>
            <button type="button" class="replay-add-token" title="${escapeAttr(t('rp.addTokenTitle'))}">${t('rp.addToken')}</button>
          </span>
        </div>
        ${battlefieldRowsHtml(bf, p, s)}
      </div>`;
  }

  // Groups battlefield permanents the same way as the Goldfisch board: hosts
  // with their attachments (Auras/Equipment) framed together, split into
  // creatures / lands / other rows (RULE 301/303).
  function battlefieldRowsHtml(bf, p, s) {
    if (!bf.length) return '<p class="empty-state">leer</p>';
    const byId = new Map(bf.map((o) => [o.instance_id, o]));

    const attachments = new Map(); // host instance_id -> [attached obj]
    const attachedIds = new Set();
    for (const o of bf) {
      if (o.attached_to != null && byId.has(o.attached_to)) {
        if (!attachments.has(o.attached_to)) attachments.set(o.attached_to, []);
        attachments.get(o.attached_to).push(o);
        attachedIds.add(o.instance_id);
      }
    }
    const top = bf.filter((o) => !attachedIds.has(o.instance_id));

    const creatures = top.filter((o) => o.is_creature);
    const lands = top.filter((o) => !o.is_creature && o.is_land);
    const other = top.filter((o) => !o.is_creature && !o.is_land);

    // A Reconfigure permanent is itself a legal Aura/Equipment target while
    // unattached, then becomes non-creature "equipment" once attached to a
    // host (RULE 702.151b) — so its own attachments form a second chain link
    // (Aura/Equipment -> Reconfigure permanent -> host). Render that nested,
    // rather than dropping it: only `top`-level hosts were being walked here,
    // so anything attached to an *attachment* never appeared at all.
    const renderAttached = (o) => {
      const card = renderCard(o, p, s);
      const nested = attachments.get(o.instance_id);
      if (!nested || !nested.length) return card;
      return card + nested.map(renderAttached).join('');
    };

    const renderObj = (o) => {
      const host = renderCard(o, p, s);
      const atts = attachments.get(o.instance_id);
      if (!atts || !atts.length) return host;
      const attached = atts.map(renderAttached).join('');
      return `<div class="gf-attach-group" title="${escapeAttr(t('bd.bf.attachTitle'))}">${host}${attached}</div>`;
    };

    const rowHtml = (label, list) =>
      `<div class="gf-bf-row">
        <span class="gf-bf-row-label">${label} (${list.length})</span>
        ${list.length ? `<div class="replay-zone-cards">${list.map(renderObj).join('')}</div>` : '<p class="empty-state">–</p>'}
      </div>`;

    const rows = threeRows
      ? [
          rowHtml(t('bd.bf.rowCreatures'), creatures),
          rowHtml(t('bd.bf.rowArtEnch'), other),
          rowHtml(t('bd.bf.rowLands'), lands),
        ]
      : [
          rowHtml(t('bd.bf.rowCreatures'), creatures),
          rowHtml(t('bd.bf.rowLandsPermanents'), other.concat(lands)),
        ];
    return `<div class="gf-bf-rows">${rows.join('')}</div>`;
  }

  // Move targets: every zone of every player (so control/owner can change),
  // shared by both the card-tile "→ Zone…" select and the library list rows.
  // A token only ever offers battlefield destinations — it ceases to exist
  // in any other zone (RULE 111.7), so the server rejects the rest anyway.
  function moveOptionsHtml(s, tokenOnly = false) {
    const zones = tokenOnly ? ZONES.filter(([z]) => z === 'battlefield') : ZONES;
    return s.players
      .map((pl) =>
        zones.map(([z, label]) =>
          `<option value='${escapeAttr(JSON.stringify({ zone: z, owner_id: pl.id }))}'>${s.players.length > 1 ? `${escapeHtml(pl.name)}: ` : ''}${escapeHtml(label)}</option>`,
        ).join(''),
      )
      .join('');
  }

  function renderCard(o, owner, s) {
    const isToken = o.is_token || (o.card_id || '').startsWith('token:');
    const face = o.transformed ? 'back' : 'front';
    const inner = !isToken && o.card_id
      ? `<img src="${cardImageUrl(o.card_id, 'small', face)}" alt="${escapeHtml(o.name)}" loading="lazy" />`
      : `<span class="replay-card-name">${escapeHtml(o.name)}</span>`;
    const classes = ['replay-card'];
    if (o.tapped) classes.push('tapped');
    if (isToken) classes.push('is-token');
    const pt = o.power != null && o.toughness != null ? `${o.power}/${o.toughness}` : '';
    const counters = Object.entries(o.counters || {});
    const hasHaste = (o.keywords || []).some((keyword) => keyword.toLowerCase() === 'haste');
    const sick = o.zone === 'battlefield' && o.is_creature && o.summoning_sick && !hasHaste;
    const badges = [
      pt ? `<span class="replay-badge">${escapeHtml(pt)}</span>` : '',
      o.loyalty != null ? `<span class="replay-badge">♦${o.loyalty}</span>` : '',
      counters.length ? `<span class="replay-badge replay-badge--counter">${counters.map(([k, v]) => `${escapeHtml(k)}×${v}`).join(' ')}</span>` : '',
      sick ? `<span class="replay-badge replay-badge--sick" title="${escapeAttr(t('rp.sickTitle'))}">💤</span>` : '',
    ].join('');
    // Draggable onto any `.replay-zone` drop target (see `wireEditor`) — the
    // "→ Zone…" dropdown this replaced also let a 2-player board reassign
    // owner/controller by dropping onto the other player's zone.
    return `
      <div class="${classes.join(' ')}" data-iid="${o.instance_id}" data-hover-card="${escapeHtml(o.name)}" title="${escapeHtml(o.name)}${pt ? ` (${pt})` : ''}" draggable="true">
        ${inner}
        ${badges ? `<div class="replay-card-badges">${badges}</div>` : ''}
        <div class="replay-card-tools">
          <button type="button" data-card-act="tap" title="${escapeAttr(t('rp.tapTitle'))}">⤵</button>
          <button type="button" data-card-act="flip" title="${escapeAttr(t('rp.flipTitle'))}">⟳</button>
          <button type="button" data-card-act="plus" title="+1/+1 Marke">＋</button>
          <button type="button" data-card-act="minus" title="−1/−1 Marke">−</button>
          <button type="button" data-card-act="counter" title="${escapeAttr(t('rp.counterAnyTitle'))}">✦</button>
          ${o.zone === 'battlefield' && o.is_creature ? `<button type="button" data-card-act="sick" class="${sick ? 'active' : ''}" title="${escapeAttr(t('rp.sickToggleTitle'))}">💤</button>` : ''}
          <button type="button" data-card-act="remove" title="${escapeAttr(t('rp.removeTitle'))}">✕</button>
        </div>
      </div>`;
  }

  function renderModal() {
    const isToken = modal.kind === 'token';
    const isLibrary = modal.kind === 'library';
    const overlay = document.createElement('div');
    overlay.className = 'replay-modal-overlay';
    overlay.innerHTML = isToken ? renderTokenForm() : isLibrary ? renderLibraryModal() : renderCardSearch();
    root.appendChild(overlay);
    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) {
        modal = null;
        render();
      }
    });
    if (isLibrary) {
      wireLibraryItems(overlay);
    } else if (isToken) {
      const q = (sel) => overlay.querySelector(sel);
      overlay.querySelectorAll('[data-preset]').forEach((btn) => {
        btn.addEventListener('click', () => {
          const preset = TOKEN_PRESETS[Number(btn.dataset.preset)];
          if (!preset) return;
          q('#replay-token-name').value = preset.name;
          q('#replay-token-type').value = preset.type_line;
          q('#replay-token-p').value = preset.power ?? '';
          q('#replay-token-t').value = preset.toughness ?? '';
          q('#replay-token-text').value = preset.oracle_text || '';
          overlay.querySelectorAll('.replay-token-color').forEach((cb) => {
            cb.checked = (preset.colors || []).includes(cb.value);
          });
        });
      });
      overlay.querySelector('#replay-token-add')?.addEventListener('click', () => {
        const colors = Array.from(overlay.querySelectorAll('.replay-token-color:checked')).map((c) => c.value);
        const power = q('#replay-token-p').value;
        const toughness = q('#replay-token-t').value;
        addToken({
          name: q('#replay-token-name').value.trim() || 'Token',
          type_line: q('#replay-token-type').value.trim() || 'Creature',
          power: power === '' ? null : Number(power),
          toughness: toughness === '' ? null : Number(toughness),
          colors,
          oracle_text: q('#replay-token-text').value.trim(),
        });
      });
    } else {
      const input = overlay.querySelector('#replay-card-query');
      // Live substring search against the already-loaded pool: only patches
      // the result `<ul>` in place (not a full `render()`) so the input
      // never loses focus/cursor position mid-keystroke.
      input?.addEventListener('input', (e) => {
        modal.query = e.target.value;
        updateLiveResults();
        const list = overlay.querySelector('.replay-search-results');
        if (list) {
          list.innerHTML = cardResultListHtml();
          wireCardResultButtons(list);
        }
      });
      input?.addEventListener('keydown', (e) => { if (e.key === 'Enter') searchCard(); });
      overlay.querySelector('#replay-card-search')?.addEventListener('click', searchCard);
      wireCardResultButtons(overlay);
    }
    overlay.querySelector('[data-modal-close]')?.addEventListener('click', () => {
      modal = null;
      render();
    });
  }

  // The add-card modal's result `<ul>` contents — shared by the initial
  // render and the live-search partial update (`input` handler above), so
  // the two stay in sync.
  function cardResultListHtml() {
    if (!modal.searched) return '';
    if (modal.tooShort) return `<li class="empty-state">Mindestens ${MIN_SEARCH_CHARS} Zeichen eingeben…</li>`;
    if (cardPool == null) return `<li class="empty-state">${t('rp.cardPoolLoading')}</li>`;
    const results = modal.results || [];
    return results.length
      ? results.map((c) => `<li><button type="button" data-add-card='${escapeAttr(JSON.stringify({ id: c.id, name: c.name }))}'>${escapeHtml(c.name)} <small>${escapeHtml(c.type_line || '')}</small></button></li>`).join('')
      : `<li class="empty-state">${escapeHtml(t('rp.nothingFound'))}</li>`;
  }

  function wireCardResultButtons(container) {
    container.querySelectorAll('[data-add-card]').forEach((el) =>
      el.addEventListener('click', () => addResolvedCard(JSON.parse(el.dataset.addCard))),
    );
  }

  function renderCardSearch() {
    return `
      <div class="replay-modal">
        <div class="replay-modal-head"><h3>${t('rp.addCardTitle')}</h3><button type="button" data-modal-close>✕</button></div>
        <div class="replay-modal-body">
          <div class="replay-search-row">
            <input type="text" id="replay-card-query" placeholder="${escapeAttr(t('rp.cardQueryPlaceholder'))}" value="${escapeAttr(modal.query || '')}" />
            <button type="button" id="replay-card-search" class="primary">${t('rp.search')}</button>
          </div>
          <ul class="replay-search-results">${cardResultListHtml()}</ul>
        </div>
      </div>`;
  }

  function renderTokenForm() {
    const presets = TOKEN_PRESETS.map((t, i) => {
      const pt = t.power != null && t.toughness != null ? `${t.power}/${t.toughness}` : '';
      return `<button type="button" class="replay-token-preset" data-preset="${i}" title="${escapeAttr(t.oracle_text || '')}">${escapeHtml(t.name)}${pt ? ` <small>${escapeHtml(pt)}</small>` : ''}</button>`;
    }).join('');
    return `
      <div class="replay-modal">
        <div class="replay-modal-head"><h3>${t('rp.addTokenTitle')}</h3><button type="button" data-modal-close>✕</button></div>
        <div class="replay-modal-body replay-token-form">
          <div class="replay-token-presets">
            <span class="replay-token-presets-label">${t('rp.tokenPresetsLabel')}</span>
            <div class="replay-token-preset-grid">${presets}</div>
          </div>
          <label>${t('rp.name')} <input type="text" id="replay-token-name" placeholder="Goblin" /></label>
          <label>Typ <input type="text" id="replay-token-type" placeholder="Creature — Goblin" value="Creature" /></label>
          <label>${t('rp.power')} <input type="number" id="replay-token-p" value="1" /></label>
          <label>${t('rp.toughness')} <input type="number" id="replay-token-t" value="1" /></label>
          <div class="replay-token-colors">Farben:
            ${COLORS.map(([v, l]) => `<label><input type="checkbox" class="replay-token-color" value="${v}" /> ${l}</label>`).join('')}
          </div>
          <label>${t('rp.abilityText')}
            <textarea id="replay-token-text" rows="2" placeholder="${escapeAttr(t('rp.tokenTextPlaceholder'))}"></textarea>
          </label>
          <button type="button" id="replay-token-add" class="primary">${t('rp.add')}</button>
        </div>
      </div>`;
  }

  function statusLine() {
    if (!status) return '';
    return `<p class="replay-status replay-status--${statusKind || 'info'}">${escapeHtml(status)}</p>`;
  }

  // --- Event wiring (editor) ---------------------------------------------

  function wireEditor() {
    const q = (sel) => root.querySelector(sel);
    q('[data-tool="new"]')?.addEventListener('click', quit);
    q('[data-tool="export"]')?.addEventListener('click', exportToFile);
    q('[data-tool="quit"]')?.addEventListener('click', quit);
    q('[data-tool="rewind"]')?.addEventListener('click', rewind);
    q('[data-tool="play-mode"]')?.addEventListener('click', enterPlayMode);
    q('#replay-import')?.addEventListener('change', (e) => importFile(e.target.files?.[0]));

    q('#replay-turn')?.addEventListener('change', (e) =>
      act({ type: 'edit_set_turn', internal_turn: Number(e.target.value) }));
    q('#replay-step')?.addEventListener('change', (e) =>
      act({ type: 'edit_set_turn', step: e.target.value }));
    q('#replay-active')?.addEventListener('change', (e) =>
      act({ type: 'edit_set_turn', active_player_id: e.target.value }));

    // Flip the static-zone column (library/graveyard/…) to the other side —
    // same toggle as the Goldfisch board's "⇄ Zonen-Seite".
    q('[data-tool="zones-side"]')?.addEventListener('click', () => {
      zonesLeft = !zonesLeft;
      setCookie('replay_zones_side', zonesLeft ? 'left' : 'right', 365);
      render();
    });

    // Battlefield 2-/3-row layout toggle (persisted client-side), same as
    // the Goldfisch board. One checkbox per player's battlefield, all bound
    // to the same shared setting.
    root.querySelectorAll('.replay-rows-toggle').forEach((el) => {
      el.addEventListener('change', (e) => {
        threeRows = e.target.checked;
        setCookie('replay_board_rows', threeRows ? '3' : '2', 365);
        render();
      });
    });

    root.querySelectorAll('.replay-player').forEach((panel) => {
      const pid = panel.dataset.player;
      panel.querySelector('.replay-life')?.addEventListener('change', (e) =>
        act({ type: 'edit_set_life', player_id: pid, value: Number(e.target.value) }));
      panel.querySelector('.replay-poison')?.addEventListener('change', (e) =>
        act({ type: 'edit_set_poison', player_id: pid, value: Number(e.target.value) }));
      panel.querySelectorAll('.replay-mana').forEach((inp) =>
        inp.addEventListener('change', (e) =>
          act({ type: 'edit_set_mana', player_id: pid, mana_type: inp.dataset.manaType, value: Number(e.target.value) })));
      panel.querySelectorAll('.replay-pcounter').forEach((inp) =>
        inp.addEventListener('change', (e) =>
          act({ type: 'edit_set_player_counter', player_id: pid, counter: inp.dataset.counter, amount: Number(e.target.value) })));
      panel.querySelector('.replay-pcounter-add')?.addEventListener('click', () => {
        const name = window.prompt(t('rp.promptCounterName'));
        if (!name) return;
        const amount = Number(window.prompt(t('rp.promptAmount'), '1') || 0);
        act({ type: 'edit_set_player_counter', player_id: pid, counter: name.trim(), amount });
      });
    });

    root.querySelectorAll('.replay-zone').forEach((zoneEl) => {
      const playerId = zoneEl.dataset.player;
      const zone = zoneEl.dataset.zone;
      zoneEl.querySelector('.replay-add-card')?.addEventListener('click', () => {
        modal = { kind: 'card', playerId, zone, query: '', results: [], searched: false, tooShort: false };
        render();
        ensureCardPool();
      });
      zoneEl.querySelector('.replay-add-token')?.addEventListener('click', () => {
        modal = { kind: 'token', playerId, zone };
        render();
      });
      zoneEl.querySelector('.replay-lib-open')?.addEventListener('click', () => {
        modal = { kind: 'library', playerId };
        render();
      });
      wireZoneDropTarget(zoneEl, playerId, zone);
    });

    root.querySelectorAll('.replay-card').forEach((cardEl) => {
      const iid = Number(cardEl.dataset.iid);
      cardEl.querySelectorAll('[data-card-act]').forEach((btn) =>
        btn.addEventListener('click', () => cardAction(iid, btn.dataset.cardAct, cardEl)));
      cardEl.addEventListener('dragstart', (e) => {
        draggedIid = iid;
        cardEl.classList.add('dragging');
        e.dataTransfer.effectAllowed = 'move';
        e.dataTransfer.setData('text/plain', String(iid));
      });
      cardEl.addEventListener('dragend', () => {
        draggedIid = null;
        cardEl.classList.remove('dragging');
      });
    });
  }

  // Drag&drop move: a card dropped onto a `.replay-zone` box moves there
  // (`edit_move_object`), replacing the old per-card "→ Zone…" dropdown. A
  // token may only land on a battlefield (RULE 111.7 — it ceases to exist
  // elsewhere), enforced here by simply not accepting the drop (no
  // `preventDefault` in `dragover` → the browser shows a "no-drop" cursor
  // and never fires `drop`); the server would reject it anyway.
  function wireZoneDropTarget(zoneEl, playerId, zone) {
    zoneEl.addEventListener('dragover', (e) => {
      if (draggedIid == null) return;
      const obj = findObject(draggedIid);
      if (!obj || (obj.is_token && zone !== 'battlefield')) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
      zoneEl.classList.add('replay-zone--drop-target');
    });
    zoneEl.addEventListener('dragleave', (e) => {
      if (!zoneEl.contains(e.relatedTarget)) zoneEl.classList.remove('replay-zone--drop-target');
    });
    zoneEl.addEventListener('drop', (e) => {
      e.preventDefault();
      zoneEl.classList.remove('replay-zone--drop-target');
      const iid = draggedIid;
      draggedIid = null;
      if (iid == null) return;
      const obj = findObject(iid);
      const alreadyThere = obj && obj.zone === zone
        && (zone === 'battlefield' ? obj.controller_id === playerId : obj.owner_id === playerId);
      if (alreadyThere) return;
      act({ type: 'edit_move_object', instance_id: iid, zone, owner_id: playerId, controller_id: playerId });
    });
  }

  function libraryAction(iid, action) {
    if (action === 'up' || action === 'down') {
      act({ type: 'edit_reorder_object', instance_id: iid, direction: action });
    } else if (action === 'remove') {
      act({ type: 'edit_remove_object', instance_id: iid });
    }
  }

  // Wires the move/up/down/remove controls of every `.replay-lib-item` row
  // found within `container` — used for the library pop-up (`renderModal`).
  function wireLibraryItems(container) {
    container.querySelectorAll('.replay-lib-item').forEach((itemEl) => {
      const iid = Number(itemEl.dataset.iid);
      itemEl.querySelectorAll('[data-lib-act]').forEach((btn) =>
        btn.addEventListener('click', () => libraryAction(iid, btn.dataset.libAct)));
      itemEl.querySelector('.replay-move')?.addEventListener('change', (e) => {
        if (!e.target.value) return;
        const { zone, owner_id } = JSON.parse(e.target.value);
        act({ type: 'edit_move_object', instance_id: iid, zone, owner_id, controller_id: owner_id });
      });
    });
  }

  function cardAction(iid, action, cardEl) {
    if (action === 'tap') {
      const tapped = cardEl.classList.contains('tapped');
      act({ type: 'edit_set_flags', instance_id: iid, tapped: !tapped });
    } else if (action === 'flip') {
      act({ type: 'edit_transform', instance_id: iid });
    } else if (action === 'sick') {
      const obj = findObject(iid);
      act({ type: 'edit_set_flags', instance_id: iid, summoning_sick: !(obj?.summoning_sick) });
    } else if (action === 'plus' || action === 'minus') {
      const obj = findObject(iid);
      const current = (obj?.counters || {})['+1/+1'] || 0;
      const next = action === 'plus' ? current + 1 : current - 1;
      act({ type: 'edit_set_counters', instance_id: iid, counter: '+1/+1', amount: next });
    } else if (action === 'counter') {
      const kind = window.prompt(t('rp.promptCounterKind'));
      if (!kind) return;
      const obj = findObject(iid);
      const current = (obj?.counters || {})[kind.trim()] || 0;
      const amount = Number(window.prompt(t('rp.promptAmount'), String(current || 1)) || 0);
      act({ type: 'edit_set_counters', instance_id: iid, counter: kind.trim(), amount });
    } else if (action === 'remove') {
      act({ type: 'edit_remove_object', instance_id: iid });
    }
  }

  function findObject(iid) {
    const s = view?.state;
    if (!s) return null;
    for (const o of s.battlefield) if (o.instance_id === iid) return o;
    for (const p of s.players) {
      for (const [z] of ZONES) {
        if (z === 'battlefield') continue;
        for (const o of p[z] || []) if (o.instance_id === iid) return o;
      }
    }
    return null;
  }

  return { mount, onShown };
}

function downloadJson(data, filename) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str == null ? '' : String(str);
  return div.innerHTML;
}

function escapeAttr(str) {
  return String(str).replace(/'/g, '&#39;').replace(/"/g, '&quot;');
}
