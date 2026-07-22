// Shared interactive game board: step the turn, play lands, tap mana, cast
// spells with the stack, attack — everything a live `GameSession` (any mode)
// supports via `legal_actions`/`apply_action`. Originally goldfishView.js's
// solo board; extracted so Replay/Puzzle mode's "Spielmodus" (play mode) can
// drive the very same board against its own session, including a second real
// player's board when the puzzle has one (goldfish's dummy has none, so it
// still renders as the old compact strip).
//
// Ownership split: this module owns the session's live game state (`view`,
// `sessionId`) and every gameplay action from here on — advance/cast/attack/
// tap/pass/rewind. "Neu starten" is deliberately *not* built in: for a
// goldfish session it can land back in the mulligan phase (a screen this
// module doesn't know how to draw), so it's the caller's job, wired in via
// `extraControls`. The caller also supplies an `onViewChange` hook to mirror
// the latest view back out (e.g. so Replay's editor screen isn't stale when
// you switch back to it).

import { getState } from './state.js';
import { sendGameAction, rewindGame, cardImageUrl, GENERIC_TOKEN_KEY } from './api.js';
import { getCookie, setCookie } from './cookies.js';

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
  // Not a real step name on its own — `DelayedTrigger.step` uses this for
  // "your next main phase" (Mana Drain-shaped), matching whichever of
  // main1/main2 begins first (`GameEngine._fire_delayed_triggers`).
  main: 'Hauptphase',
};
function labelPhase(name) {
  return PHASE_LABELS[name] || name || '—';
}
function labelStep(name) {
  return STEP_LABELS[name] || name || '—';
}

// Icon per choice kind — search, cascade and discover share the same
// "answer one of these options" shape, so one renderer covers them.
const CHOICE_ICONS = {
  search: '🔎', cascade: '🌊', discover: '🔮', replacement_order: '⚖️',
  land_tapped: '💧', order_triggers: '🔀', trigger_target: '🎯',
  enter_as_copy: '🪞', counter_unless_pays: '🚫', ward: '🛡️',
  commander_zone: '👑', trigger_mode: '🎭', add_mana_any_color: '💎',
  choose_creature_type: '🐾', choose_color: '🎨',
};

/**
 * @param {object} [opts]
 * @param {(view: object) => void} [opts.onViewChange] Called with every fresh
 *   server view (after any action/rewind/restart), so the caller can keep its
 *   own copy in sync — e.g. Replay mode reads it when switching back to the
 *   editor screen so that screen isn't stale.
 * @param {(busy: boolean) => Array<{id,label,title?,disabled?,onClick:Function}>} [opts.extraControls]
 *   Extra toolbar buttons appended after the built-in ones (Schritt/Nächste
 *   Entscheidung/Priorität/Zurücknehmen/Neu starten/Zonen-Seite) — e.g.
 *   goldfishView's "Als Replay speichern"/"Beenden", replayView's "Zurück
 *   zum Editor".
 */
export function createGameBoardView(opts = {}) {
  const onViewChange = opts.onViewChange || (() => {});
  const extraControlsFn = opts.extraControls || (() => []);

  let root = null;
  let sessionId = null;
  let view = null;
  let busy = false;
  let status = '';
  let statusKind = '';

  // Player-uploaded custom art (settings.js "Einstellungen" tab, see
  // api.js tokenImageUrl/sleeveImageUrl): `tokenImages` maps a lowercased
  // token name to an art URL (for synthesized tokens with no real Scryfall
  // art); `sleeveImageUrl` is the caller's currently-selected deck sleeve.
  // Set via `setAssets()` once the caller knows them (after resolving the
  // active deck/player) — see resolveImageUrl().
  let tokenImages = {};
  let assetsSleeveImageUrl = null;

  /** @param {{tokenImages?: Record<string,string>, sleeveImageUrl?: string|null}} assets */
  function setAssets(assets = {}) {
    tokenImages = assets.tokenImages || {};
    assetsSleeveImageUrl = assets.sleeveImageUrl || null;
    render();
  }

  // Battlefield layout: permanents split across rows by card type (creatures
  // / artifacts+enchantments / lands). Two rows by default; the checkbox
  // promotes lands to their own third row (persisted client-side).
  let threeRows = getCookie('gf_board_rows') === '3';
  // Optional, default-hidden "static effects / layer trace" panel (RULE 613).
  let showStatics = getCookie('gf_show_statics') === '1';
  // Play-area layout: the static-zone column (command/library/graveyard/
  // exile) sits on one side, battlefield+hand on the other; toggleable side.
  let zonesLeft = getCookie('gf_zones_side') === 'left';
  // The stack overlays the board while non-empty; can be pushed aside to a
  // compact corner card so priority actions can be taken on the board below.
  let stackAside = false;
  // Attacking creatures whose "choose a defender" submenu is open (2+ legal
  // defenders, RULE 508.1a).
  const attackMenuOpen = new Set();
  // A targeting spell/ability (RULE 115) mid-cast: `{ instanceId, requirements,
  // reqIndex, targets: [], x, send }` or null. See `castTargetHtml`.
  let castTargeting = null;
  // A single requirement with `count > 1` (RULE 115.1a generalized to N>=2 —
  // "destroy two target creatures"/"up to two target artifacts") is expanded
  // into `count` synthetic one-per-round requirements sharing the same
  // options, reusing the exact same "pick N from one pool, one at a time"
  // modal + `excludePicked` de-dup a "tap N untapped <type>s you control"
  // cost choice already uses (`data-tap-choice-start` below) — an optional
  // requirement's existing per-round "∅ Kein Ziel" decline button then
  // doubles as "stop after fewer than N", giving "up to N" for free.
  //
  // `distinct_controllers` (Run Away Together/Protector of the Wastes-
  // shaped "N target creatures controlled by different players") is the one
  // cross-target constraint modeled so far (`targeting.TargetSpec.
  // distinct_controllers`) — `excludeControllers` mirrors `excludePicked`
  // exactly, just keyed on an already-picked round's `controller_id`
  // instead of its `instance_id`, so a later round's pool drops every
  // permanent sharing a controller with anything already chosen.
  function expandMultiTargetRequirements(requirements) {
    const expanded = [];
    let excludePicked = false;
    let excludeControllers = false;
    for (const req of requirements) {
      const count = req.count || 1;
      if (count > 1) excludePicked = true;
      if (req.distinct_controllers) excludeControllers = true;
      for (let i = 0; i < count; i += 1) expanded.push(req);
    }
    return { requirements: expanded, excludePicked, excludeControllers };
  }
  // The user's current drag-and-drop arrangement of a pending `replacement_
  // order` choice's options (RULE 616.1) — an array of option ids, reset
  // whenever a fresh choice with a different option set appears. See
  // `replacementOrderHtml`/`confirmReplacementOrder`.
  let replacementOrderDraft = null;

  function mount(el) {
    root = el;
  }

  /** Begin driving `sessionId`, rendering `initialView` immediately. */
  function start(sid, initialView) {
    sessionId = sid;
    applyView(initialView);
  }

  /** Feed in a view obtained some other way (rare — actions normally do this themselves). */
  function refresh(newView) {
    applyView(newView);
  }

  function setStatus(text, kind = '') {
    status = text;
    statusKind = kind;
  }

  function applyView(data) {
    view = data;
    castTargeting = null;
    onViewChange(data);
    render();
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
        setStatus('Spielsitzung abgelaufen.', 'warning');
      } else {
        setStatus(`Fehler (${res.status}).`, 'warning');
      }
    });
  }

  async function rewind() {
    if (!sessionId) return;
    await withBusy(async () => {
      const res = await rewindGame(sessionId, 1);
      if (res.ok) {
        applyView(res.data);
        setStatus('Letzter Zug rückgängig gemacht.', 'ok');
      } else {
        setStatus(`Rückgängig fehlgeschlagen (${res.status}).`, 'warning');
      }
    });
  }

  // --- Rendering ------------------------------------------------------------

  function render() {
    if (!root || !view) return;
    const s = view.state;
    const dummy = s.players.find((p) => p.is_dummy) || null;
    const live = s.players.filter((p) => !p.is_dummy);
    const actions = view.legal_actions || [];
    const gameOver = s.game_over;
    const pending = s.pending_choice;

    // Index the per-object actions so each card can show its own buttons
    // directly underneath it. `legal_actions` is already scoped server-side
    // to the active player, so this naturally only lights up whoever's turn
    // it is — works the same whether there's one live player (goldfish) or
    // two (a Replay puzzle's play mode).
    const byInstance = {};
    for (const a of actions) {
      if (a.instance_id == null) continue;
      (byInstance[a.instance_id] ||= []).push(a);
    }
    const stackNonEmpty = s.stack.length > 0;
    if (!stackNonEmpty) stackAside = false;

    root.innerHTML = `
      <div class="goldfish${pending || castTargeting ? ' choosing' : ''}">
        <div class="gf-topbar">
          <div class="gf-turninfo">
            <span class="gf-turn">Zug ${s.turn_number}</span>
            <span class="gf-step">${escapeHtml(labelPhase(s.current_phase))} · ${escapeHtml(labelStep(s.current_step))}</span>
            ${live.length > 1 ? `<span class="gf-active-player">Aktiv: ${escapeHtml(s.players.find((p) => p.id === s.active_player_id)?.name || '')}</span>` : ''}
            ${s.day_night ? `<span class="gf-daynight gf-daynight-${s.day_night}">${s.day_night === 'night' ? '🌙 Nacht' : '☀️ Tag'}</span>` : ''}
          </div>
        </div>

        ${dummy ? opponentStripHtml(dummy) : ''}

        ${gameOver ? gameOverHtml(s, live[0]) : ''}
        ${statusHtml()}
        ${pending ? pendingChoiceHtml(pending) : ''}
        ${castTargeting ? castTargetModalHtml() : ''}

        ${controlsHtml(stackNonEmpty, pending, gameOver)}

        ${live.map((p) => playerBoardHtml(p, s, byInstance, pending)).join('')}

        ${stackNonEmpty && !pending ? stackOverlayHtml(s, stackAside) : ''}

        ${delayedTriggersPanelHtml(view)}

        ${moveLogHtml(view.move_log)}
      </div>
    `;
    wire();
  }

  function controlsHtml(stackNonEmpty, pending, gameOver) {
    const extra = extraControlsFn(busy)
      .map(
        (c) =>
          `<button type="button" data-extra="${escapeAttr(c.id)}" title="${escapeAttr(c.title || '')}" ${busy || c.disabled ? 'disabled' : ''}>${c.label}</button>`,
      )
      .join('');
    return `
      <div class="gf-controls">
        <button id="gf-advance" type="button" class="primary" ${busy || gameOver || pending ? 'disabled' : ''}>Nächster Schritt →</button>
        <button id="gf-next-decision" type="button" title="Überspringt Schritte ohne Entscheidung und hält bei der nächsten Wahl des aktiven Spielers" ${busy || gameOver || pending ? 'disabled' : ''}>⏭ Nächste Entscheidung</button>
        ${stackNonEmpty && !pending ? `<button type="button" data-action='${escapeAttr(JSON.stringify({ type: 'pass_priority' }))}'>Priorität abgeben (Stack auflösen)</button>` : ''}
        <button id="gf-rewind" type="button" ${busy || !view.can_rewind ? 'disabled' : ''}>↶ Zurücknehmen</button>
        <button id="gf-zones-side" type="button" title="Zonen-Spalte (Bibliothek, Friedhof …) auf die andere Seite legen">⇄ Zonen-Seite</button>
        ${extra}
      </div>`;
  }

  // One player's full board: mana/life header, command/library/graveyard/
  // exile column, battlefield (row-grouped by type) + hand.
  function playerBoardHtml(p, s, byInstance, pending) {
    const bf = s.battlefield.filter((o) => o.controller_id === p.id);
    return `
      <section class="gf-player-board">
        <header class="gf-player-board-head">
          <h3>${escapeHtml(p.name)}</h3>
          ${manaPoolHtml(p.mana_pool)}
          ${lifeBox('Leben', p.life)}
        </header>
        <div class="gf-play gf-zones-${zonesLeft ? 'left' : 'right'}">
          <aside class="gf-side">
            <div class="gf-zone gf-command">
              <h4>Command Zone</h4>
              ${objGrid(p.command, '–', byInstance, pending)}
            </div>
            <div class="gf-zone gf-library">
              <h4>Bibliothek</h4>
              <p class="library-count">${p.library_count} Karten</p>
              ${libraryTopHtml(p, byInstance, pending)}
            </div>
            <div class="gf-zone gf-graveyard">
              <h4>Friedhof (${p.graveyard.length})</h4>
              ${zoneListHtml(p.graveyard, 'leer')}
            </div>
            <div class="gf-zone gf-exile">
              <h4>Exil (${p.exile.length})</h4>
              ${objGrid(p.exile, 'leer', byInstance, pending)}
            </div>
          </aside>

          <div class="gf-main">
            <div class="gf-zone gf-battlefield">
              <div class="gf-bf-head">
                <h4>Battlefield (${bf.length})</h4>
                <label class="gf-bf-toggle" title="Länder in eine eigene, dritte Reihe legen">
                  <input type="checkbox" class="gf-rows-toggle" ${threeRows ? 'checked' : ''} />
                  Länder in eigener Reihe
                </label>
                <label class="gf-bf-toggle" title="Statische Effekte und die Layer-Herleitung (Regel 613) anzeigen">
                  <input type="checkbox" class="gf-statics-toggle" ${showStatics ? 'checked' : ''} />
                  🔍 Statische Effekte
                </label>
              </div>
              ${battlefieldHtml(bf, byInstance, pending)}
            </div>

            ${showStatics ? staticEffectsPanelHtml(view, s) : ''}

            ${exileCastableHtml(p, s, byInstance, pending)}

            <div class="gf-zone gf-hand">
              <h4>Hand (${p.hand.length})</h4>
              ${objGrid(p.hand, 'leer', byInstance, pending)}
            </div>
          </div>
        </div>
      </section>`;
  }

  // The top card of a library is normally face-down (`library_count` is
  // all the board shows). A permanent granting "play with the top card of
  // your library revealed" (Oracle of Mul Daya/Glarb, Calamity's Augur-
  // shaped) flips `top_library_visible[player_id]` server-side
  // (`services/game_session.py`'s `view()`) — the card itself is already
  // on the wire either way (`Player.to_dict()`'s `library` array), so this
  // only decides whether to *render* it. Whether it's actually playable/
  // castable from there is conveyed the ordinary way: `objGrid` attaches
  // whatever `play_land`/`cast_spell` buttons `legal_actions` offered for
  // that instance_id, same as any hand card — a look-only permission (no
  // matching legal action) simply shows the card with no buttons.
  function libraryTopHtml(p, byInstance, pending) {
    if (!view.top_library_visible?.[p.id] || !p.library.length) return '';
    const top = p.library[p.library.length - 1];
    return `
      <p class="library-top-hint">👁️ Oberste Karte sichtbar</p>
      ${objGrid([top], '', byInstance, pending)}
    `;
  }

  function playerName(id) {
    const p = (view.state?.players || []).find((pl) => pl.id === id);
    return p ? p.name : id;
  }

  // A pending choice is rendered as a modal popup for the deciding player:
  // the board behind it is dimmed/locked (`.goldfish.choosing`) so the only
  // thing to do is answer. Each server-provided option becomes one button —
  // except `replacement_order` (RULE 616.1), which gets a drag-and-drop
  // reorderable list instead (see `replacementOrderHtml`).
  function pendingChoiceHtml(pending) {
    const icon = CHOICE_ICONS[pending.kind] || '❔';
    const heading = pending.prompt || pending.description || 'Entscheidung nötig';
    const body = pending.kind === 'replacement_order'
      ? replacementOrderHtml(pending)
      : simpleChoiceButtonsHtml(pending);

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
          ${body}
        </div>
      </div>
    `;
  }

  function simpleChoiceButtonsHtml(pending) {
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

    return `<div class="gf-choice-options">${buttons}</div>`;
  }

  // RULE 616.1: 2+ simultaneously-applicable replacement effects (e.g.
  // Doubling Season + Parallel Lives, or Furnace of Rath + Torbran) are
  // ordered by the affected player. The server only ever asks "which one
  // applies *next*" (RULE 616.1f: applying one can expose new ones — the
  // set the choice re-offers can genuinely change), so a full drag-and-drop
  // arrangement is a client-side convenience: the player drags all
  // currently-offered effects into their desired order, and confirming
  // replays that order as a sequence of single picks (`confirmReplacementOrder`).
  function replacementOrderHtml(pending) {
    const options = pending.options || [];
    const ids = options.map((o) => o.id);
    // (Re)seed the draft whenever the offered option set doesn't match what
    // was last dragged (a fresh choice, or the previous one was just
    // answered and the remaining effects re-offered).
    if (!replacementOrderDraft
        || replacementOrderDraft.length !== ids.length
        || !ids.every((id) => replacementOrderDraft.includes(id))) {
      replacementOrderDraft = ids.slice();
    }
    const byId = Object.fromEntries(options.map((o) => [o.id, o]));
    const items = replacementOrderDraft
      .map((id, i) => {
        const opt = byId[id];
        if (!opt) return '';
        return `<li class="gf-reorder-item" draggable="true" data-id="${escapeAttr(id)}">
          <span class="gf-reorder-handle" aria-hidden="true">⠿</span>
          <span class="gf-reorder-index">${i + 1}.</span>
          <span class="gf-reorder-label">${escapeHtml(opt.label || opt.id)}</span>
        </li>`;
      })
      .join('');
    return `
      <p class="gf-reorder-hint">Per Drag &amp; Drop in die gewünschte Reihenfolge bringen — der oberste Effekt wird zuerst angewendet.</p>
      <ul class="gf-reorder-list">${items}</ul>
      <div class="gf-modal-foot">
        <button type="button" class="primary" data-reorder-confirm>Bestätigen</button>
      </div>
    `;
  }

  // Replays the player's dragged order as a sequence of single `choose`
  // picks, matching each step against the *server's own* freshly re-offered
  // options (RULE 616.1f can change that set) rather than blindly trusting
  // the draft — if a step's id is no longer offered, or a different pending
  // choice shows up instead, the auto-play stops there and whatever the
  // server returned is simply shown as-is (safe: it never submits a stale
  // or mismatched pick, it just stops automating).
  async function confirmReplacementOrder(order) {
    if (!sessionId || !order || !order.length) return;
    await withBusy(async () => {
      let remaining = order.slice();
      while (remaining.length) {
        const pending = view.state?.pending_choice;
        if (!pending || pending.kind !== 'replacement_order') break;
        const opt = (pending.options || []).find((o) => o.id === remaining[0]);
        if (!opt) break;
        const res = await sendGameAction(sessionId, {
          type: 'choose', option_id: opt.id, instance_id: opt.instance_id, name: opt.label,
        });
        if (!res.ok) {
          setStatus(`Aktion nicht erlaubt: ${res.data?.detail ?? res.status}`, 'warning');
          break;
        }
        applyView(res.data);
        remaining = remaining.slice(1);
      }
    });
    replacementOrderDraft = null;
  }

  // Anchor each per-card effect popover (top layer) at its Σ-badge when it
  // opens — the top layer otherwise centres it — flipping above / clamping to
  // the viewport so it never spills off-screen.
  function positionEffectPopover(pop, badge) {
    const r = badge.getBoundingClientRect();
    const pw = pop.offsetWidth;
    const ph = pop.offsetHeight;
    const margin = 8;
    let left = Math.min(r.left, window.innerWidth - pw - margin);
    left = Math.max(margin, left);
    let top = r.bottom + 4;
    if (top + ph > window.innerHeight - margin) top = r.top - ph - 4; // flip above
    top = Math.max(margin, top);
    pop.style.left = `${left}px`;
    pop.style.top = `${top}px`;
  }

  function wireEffectPopovers() {
    root.querySelectorAll('.gf-effects-pop').forEach((pop) => {
      const badge = root.querySelector(`[popovertarget="${CSS.escape(pop.id)}"]`);
      if (!badge) return;
      pop.addEventListener('toggle', (e) => {
        if (e.newState === 'open') positionEffectPopover(pop, badge);
      });
    });
  }

  function wire() {
    wireEffectPopovers();
    root.querySelector('#gf-advance')?.addEventListener('click', () => act({ type: 'advance_step' }));
    root.querySelector('#gf-next-decision')?.addEventListener('click', () => act({ type: 'advance_to_decision' }));
    root.querySelector('#gf-rewind')?.addEventListener('click', rewind);

    root.querySelectorAll('[data-extra]').forEach((el) => {
      const control = extraControlsFn(busy).find((c) => c.id === el.dataset.extra);
      if (control) el.addEventListener('click', control.onClick);
    });

    root.querySelectorAll('[data-action]').forEach((el) => {
      el.addEventListener('click', () => {
        act(JSON.parse(el.dataset.action));
      });
    });

    // RULE 616.1 replacement-order popup: drag & drop reordering. Dragging
    // reorders the list purely client-side (`replacementOrderDraft` is only
    // read again on the next render/confirm); "Bestätigen" replays the final
    // order via `confirmReplacementOrder`.
    const reorderList = root.querySelector('.gf-reorder-list');
    if (reorderList) {
      reorderList.querySelectorAll('.gf-reorder-item').forEach((el) => {
        el.addEventListener('dragstart', () => {
          el.classList.add('dragging');
        });
        el.addEventListener('dragend', () => el.classList.remove('dragging'));
        el.addEventListener('dragover', (e) => {
          e.preventDefault();
          const dragging = reorderList.querySelector('.dragging');
          if (!dragging || dragging === el) return;
          const rect = el.getBoundingClientRect();
          const before = (e.clientY - rect.top) < rect.height / 2;
          reorderList.insertBefore(dragging, before ? el : el.nextSibling);
        });
        el.addEventListener('drop', (e) => e.preventDefault());
      });
      root.querySelector('[data-reorder-confirm]')?.addEventListener('click', () => {
        const order = Array.from(reorderList.querySelectorAll('.gf-reorder-item')).map((li) => li.dataset.id);
        confirmReplacementOrder(order);
      });
    }

    // Battlefield 2-/3-row layout toggle (persisted, one checkbox per board).
    root.querySelectorAll('.gf-rows-toggle').forEach((el) => {
      el.addEventListener('change', (e) => {
        threeRows = e.target.checked;
        setCookie('gf_board_rows', threeRows ? '3' : '2', 365);
        render();
      });
    });

    // Static-effects / layer-trace panel toggle (persisted client-side).
    root.querySelectorAll('.gf-statics-toggle').forEach((el) => {
      el.addEventListener('change', (e) => {
        showStatics = e.target.checked;
        setCookie('gf_show_statics', showStatics ? '1' : '0', 365);
        render();
      });
    });

    // Flip the static-zone column (library/graveyard/…) to the other side.
    root.querySelector('#gf-zones-side')?.addEventListener('click', () => {
      zonesLeft = !zonesLeft;
      setCookie('gf_zones_side', zonesLeft ? 'left' : 'right', 365);
      render();
    });

    // Push the stack overlay aside (or bring it back).
    root.querySelector('[data-stack-aside]')?.addEventListener('click', () => {
      stackAside = !stackAside;
      render();
    });

    // Expand/collapse a creature's "choose a defender" submenu.
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
        const { iid, face } = JSON.parse(el.dataset.castX);
        const input = root.querySelector(`[data-x-input="${xKey(iid, face)}"]`);
        const x = Math.max(0, Math.floor(Number(input?.value) || 0));
        const kicked = readKicker(iid, face);
        act({ type: 'cast_spell', instance_id: iid, x, face, kicked });
      });
    });

    root.querySelectorAll('[data-activate-x]').forEach((el) => {
      el.addEventListener('click', () => {
        const { iid, ability_index } = JSON.parse(el.dataset.activateX);
        const input = root.querySelector(`[data-x-input="${iid}"]`);
        const x = Math.max(0, Math.floor(Number(input?.value) || 0));
        act({ type: 'activate_ability', instance_id: iid, ability_index, x });
      });
    });

    root.querySelectorAll('[data-cast-target-start]').forEach((el) => {
      el.addEventListener('click', () => {
        const info = JSON.parse(el.dataset.castTargetStart);
        const iid = Number(info.iid);
        const action = findTargetableAction(iid, info.type, info.ability_index, info.face);
        if (!action) return;
        const input = root.querySelector(`[data-x-input="${xKey(iid, info.face)}"]`);
        const x = action.has_x ? Math.max(0, Math.floor(Number(input?.value) || 0)) : 0;
        const kicked = action.has_kicker ? readKicker(iid, info.face) : 0;
        const send = info.type === 'activate_ability'
          ? { type: 'activate_ability', instance_id: iid, ability_index: info.ability_index, name: action.name }
          : { type: 'cast_spell', instance_id: iid, name: action.name, face: info.face, kicked };
        const { requirements, excludePicked, excludeControllers } = expandMultiTargetRequirements(action.targets || []);
        castTargeting = {
          instanceId: iid, requirements, reqIndex: 0, targets: [], x, send,
          excludePicked, excludeControllers,
        };
        finishCastIfReady();
      });
    });

    root.querySelectorAll('[data-cast-target-pick]').forEach((el) => {
      el.addEventListener('click', () => {
        const { instance_id: iid, target, controller_id: controllerId } = JSON.parse(el.dataset.castTargetPick);
        if (!castTargeting || castTargeting.instanceId !== iid) return;
        if (target !== null) {
          castTargeting.targets.push(target);
          // Tracked separately from `target` (the wire-format pick sent to
          // the server) purely for `excludeControllers`'s client-side
          // per-round filtering — see `castTargetModalHtml`.
          (castTargeting.pickedControllers ||= []).push(controllerId ?? null);
        }
        castTargeting.reqIndex += 1;
        finishCastIfReady();
      });
    });

    root.querySelectorAll('[data-cast-target-cancel]').forEach((el) => {
      el.addEventListener('click', () => {
        castTargeting = null;
        render();
      });
    });

    // RULE 605.1a "any combination of colours" split builder's confirm
    // button: reads its own container's number inputs, rejects a sum that
    // doesn't match the ability's fixed/variable total client-side (the
    // server's own `validate_color_split` would reject it too, but catching
    // it here avoids a round-trip for the common "forgot to fill it in" slip).
    root.querySelectorAll('.gf-mana-split').forEach((container) => {
      container.querySelector('[data-split-confirm]')?.addEventListener('click', () => {
        const total = Number(container.dataset.splitTotal);
        const split = {};
        let sum = 0;
        container.querySelectorAll('[data-split-color]').forEach((inp) => {
          const n = Math.max(0, Math.floor(Number(inp.value) || 0));
          if (n > 0) split[inp.dataset.splitColor] = n;
          sum += n;
        });
        if (sum !== total) {
          setStatus(`Summe muss genau ${total} sein (aktuell ${sum}).`, 'warning');
          render();
          return;
        }
        const info = JSON.parse(container.dataset.splitAction);
        act({ ...info, color_split: split });
      });
    });

    root.querySelectorAll('[data-tap-choice-start]').forEach((el) => {
      el.addEventListener('click', () => {
        const info = JSON.parse(el.dataset.tapChoiceStart);
        const iid = Number(info.iid);
        const action = (view?.legal_actions || []).find(
          (a) => a.type === info.type && a.instance_id === iid && a.ability_index === info.ability_index,
        );
        if (!action || !action.tap_cost) return;
        const { count, options } = action.tap_cost;
        // One synthetic "requirement" per permanent to tap — reuses the
        // same one-pick-at-a-time modal RULE 115 targets use, since it's
        // the same UX (choose N from a pool); `excludePicked` stops the
        // same permanent being picked twice. `isTapChoice` (not a RULE 115
        // target at all — a cost) picks the "pay a cost" heading/glyph and
        // the `tap_choices` dispatch in `finishCastIfReady`, distinct from a
        // real multi-target requirement's own `excludePicked` (RULE 115.1a
        // "N target X", `expandMultiTargetRequirements`) which still sends
        // `targets`.
        const requirements = Array.from({ length: count }, () => ({
          label: 'zu tappende Kreatur', options, optional: false,
        }));
        const send = info.type === 'activate_ability'
          ? { type: 'activate_ability', instance_id: iid, ability_index: info.ability_index }
          : { type: 'tap_for_mana', instance_id: iid, ability_index: info.ability_index, option_index: info.option_index };
        castTargeting = {
          instanceId: iid, requirements, reqIndex: 0, targets: [], x: 0, send,
          excludePicked: true, isTapChoice: true,
        };
        finishCastIfReady();
      });
    });
  }

  // Modal-DFC (RULE 712.10) actions for the same card differ only by
  // `face` — key any face-scoped DOM lookup on `instance_id:face` so a
  // card offering both faces at once (e.g. both `has_x`) doesn't collide
  // on a bare instance_id.
  function xKey(instanceId, face) {
    return face ? `${instanceId}:${face}` : String(instanceId);
  }

  // Kicker/Multikicker (RULE 702.33): same face-scoped keying as `xKey`, and
  // the same "read the adjacent input at click time" idiom as `x`.
  function kickerKey(instanceId, face) {
    return face ? `${instanceId}:${face}` : String(instanceId);
  }

  function readKicker(instanceId, face) {
    const input = root.querySelector(`[data-kicker-input="${kickerKey(instanceId, face)}"]`);
    return Math.max(0, Math.floor(Number(input?.value) || 0));
  }

  function findTargetableAction(iid, type, abilityIndex, face) {
    return (view?.legal_actions || []).find(
      (a) =>
        a.type === type &&
        a.instance_id === iid &&
        (type !== 'activate_ability' || a.ability_index === abilityIndex) &&
        (a.face || undefined) === (face || undefined),
    );
  }

  function finishCastIfReady() {
    if (!castTargeting) return;
    if (castTargeting.reqIndex >= castTargeting.requirements.length) {
      const { send, targets, x, isTapChoice } = castTargeting;
      castTargeting = null;
      if (isTapChoice) {
        // A "tap N untapped <type>s you control" cost choice (RULE 602.1),
        // not a RULE 115 target — send the picked instance ids as
        // `tap_choices` instead of `targets`.
        act({ ...send, tap_choices: targets.map((t) => t.instance_id) });
      } else {
        act({ ...send, targets, x });
      }
    } else {
      render();
    }
  }

  // --- Rendering helpers ------------------------------------------------

  // The battlefield, laid out in rows by card type (creatures / artifacts &
  // enchantments / lands). Attachments (Auras, Equipment — RULE 301/303) are
  // pulled out of the flow and drawn inside a dashed group box around the
  // permanent they're attached to, rather than as loose cards.
  function battlefieldHtml(objs, byInstance = {}, pending = null) {
    if (!objs.length) return '<p class="empty-state">Keine Permanents</p>';
    const imageCache = getState().imageCache;
    const byId = new Map(objs.map((o) => [o.instance_id, o]));

    const attachments = new Map();
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

    // A Reconfigure permanent is itself a legal Aura/Equipment target while
    // unattached, then becomes non-creature "equipment" once attached to a
    // host (RULE 702.151b) — so its own attachments form a second chain link
    // (Aura/Equipment -> Reconfigure permanent -> host). Render that nested,
    // rather than dropping it: only `top`-level hosts were being walked here,
    // so anything attached to an *attachment* never appeared at all.
    const renderAttached = (o) => {
      const card = objCard(o, imageCache, pending ? [] : byInstance[o.instance_id] || []);
      const nested = attachments.get(o.instance_id);
      if (!nested || !nested.length) return card;
      return card + nested.map(renderAttached).join('');
    };

    const renderObj = (o) => {
      const actions = pending ? [] : byInstance[o.instance_id] || [];
      const host = objCard(o, imageCache, actions);
      const atts = attachments.get(o.instance_id);
      if (!atts || !atts.length) return host;
      const attached = atts.map(renderAttached).join('');
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

  // A spell's tile shows the spell's own card. A triggered/activated
  // ability has no card of its own on the stack (RULE 601 vs. 602/603) —
  // its tile instead shows the *source permanent*'s card (`item.source`,
  // `StackItem.source`) with the ability's text overlaid on top of the art,
  // plus a small 🔗 link back to that source (both the overlay text and the
  // link exist specifically so an ability waiting to resolve is never just
  // an unlabeled text box — see ToDo/Done "Stack source display").
  function stackItemHtml(item, index, total) {
    const imageCache = getState().imageCache;
    const isAbility = item.kind === 'ability';
    const visual = item.object || (isAbility ? item.source : null);
    const abilityText = isAbility ? (item.description || item.kind) : null;
    const displayName = visual ? visual.name : (abilityText || item.kind);
    const imageUrl = visual ? resolveImageUrl(visual, imageCache) : null;
    // With art to overlay onto, an ability shows its source's image with the
    // ability text banner-ed on top; without art (no source, or unresolved
    // art) it falls back to plain text — same as before this feature.
    const showOverlay = isAbility && abilityText && imageUrl;
    const inner = imageUrl
      ? `<img src="${imageUrl}" alt="${escapeHtml(displayName)}" loading="lazy" />`
      : escapeHtml(showOverlay ? displayName : (abilityText || displayName));
    const classes = ['card'];
    if (imageUrl) classes.push('has-image');
    const badge = stackKindBadge(item);
    const isTop = index === total - 1;
    const order =
      total > 1
        ? `<span class="gf-stack-order">${isTop ? 'oben – löst zuerst auf' : `#${total - index}`}</span>`
        : '';
    const overlay = showOverlay
      ? `<div class="gf-stack-ability-overlay">${escapeHtml(abilityText)}</div>`
      : '';
    const link = showOverlay
      ? `<button type="button" class="gf-stack-source-link" data-hover-card="${escapeHtml(visual.name)}" title="Quelle: ${escapeHtml(visual.name)}">🔗</button>`
      : '';
    return `
      <div class="gf-card-slot gf-stack-item${isTop ? ' is-top' : ''}">
        <span class="gf-stack-badge gf-stack-badge--${badge.cls}">${badge.icon} ${escapeHtml(badge.label)}</span>
        <div class="${classes.join(' ')}" data-hover-card="${escapeHtml(displayName)}" title="${escapeHtml(displayName)}">
          ${inner}
          ${overlay}
          ${link}
        </div>
        ${order}
      </div>`;
  }

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

  function stackKindBadge(item) {
    if (item.category === 'triggered_ability') {
      return { cls: 'triggered', icon: '⚡', label: 'Ausgelöste Fähigkeit' };
    }
    if (item.category === 'activated_ability') {
      return { cls: 'activated', icon: '🔧', label: 'Aktivierte Fähigkeit' };
    }
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

  function zoneListHtml(objs, empty) {
    if (!objs.length) return `<p class="empty-state">${empty}</p>`;
    return `<ul class="gf-zone-list">${objs
      .map((o) => `<li data-hover-card="${escapeHtml(o.name)}">${escapeHtml(o.name)}</li>`)
      .join('')}</ul>`;
  }

  // Art URL for a game object: prefer the by-name `imageCache` (populated
  // from a deck import — see state.js), but fall back to building the URL
  // straight from the object's own `card_id` (always present on non-tokens,
  // see GameObject.to_dict) so objects added directly in Replay/Puzzle mode
  // (never resolved into imageCache) still show art in Spielmodus.
  function resolveImageUrl(o, imageCache) {
    // RULE 701.20a: a card exiled face down (Beseech the Mirror) shows its
    // back, not its art — the one place the sleeve fallback below has a
    // real, reachable use today. Checked before the name cache so a card
    // whose art is already loaded doesn't leak through it.
    if (o.face_down_in_exile) return assetsSleeveImageUrl || null;
    const cached = imageCache?.get((o.name || '').toLowerCase());
    if (cached?.small) return cached.small;
    const isToken = o.is_token || (o.card_id || '').startsWith('token:');
    if (isToken) {
      const custom = tokenImages[(o.name || '').toLowerCase()];
      if (custom) return custom;
      // A face-down/transformed token (e.g. a token copy of a flipped DFC,
      // RULE 707) has no real art for its back — fall back to the
      // player's chosen sleeve backside instead of a blank tile.
      if (o.transformed && assetsSleeveImageUrl) return assetsSleeveImageUrl;
      // No specific art for this token by name (typically an ad hoc token
      // an effect synthesized inline, e.g. "1/1 white Soldier", which has
      // no catalogue entry to upload art against by exact name) — the
      // player's "generic" token image (settings.js) covers all of these.
      return tokenImages[GENERIC_TOKEN_KEY] || null;
    }
    if (!o.card_id) return null;
    return cardImageUrl(o.card_id, 'small', o.transformed ? 'back' : 'front');
  }

  function objCard(o, imageCache, cardActions) {
    const imageUrl = resolveImageUrl(o, imageCache);
    const inner = imageUrl
      ? `<img src="${imageUrl}" alt="${escapeHtml(o.name)}" loading="lazy" />`
      : escapeHtml(o.name);
    const classes = ['card'];
    if (imageUrl) classes.push('has-image');
    if (o.tapped) classes.push('tapped');
    if (o.summoning_sick) classes.push('summoning-sick');
    if (o.attacking) classes.push('attacking');
    const pt = o.power != null && o.toughness != null ? ` (${o.power}/${o.toughness})` : '';
    const buttons = cardActionButtons(cardActions);
    const attackBadge = o.attacking
      ? `<span class="gf-attacking-badge">⚔️${o.combat_defender ? ` ${escapeHtml(o.combat_defender.label || '')}` : ''}</span>`
      : '';
    // RULE 606: a planeswalker's loyalty gets its own badge (mirrors the
    // ♦{loyalty} glyph on the Replay board editor) rather than being read
    // off the generic counter badge, which would otherwise show it twice
    // (`counters` also carries a "loyalty" key — GameObject.loyalty reads it).
    const loyaltyBadge = o.is_planeswalker && o.loyalty != null
      ? `<span class="gf-loyalty-badge">◆ ${o.loyalty}</span>`
      : '';
    const counterEntries = Object.entries(o.counters || {})
      .filter(([k]) => !(o.is_planeswalker && k === 'loyalty'));
    const counterBadge = counterEntries.length
      ? `<span class="gf-counter-badge">${counterEntries.map(([k, v]) => `${escapeHtml(k)}×${v}`).join(' · ')}</span>`
      : '';
    const keywordBadge = (o.keywords && o.keywords.length)
      ? `<span class="gf-keyword-badge" title="${escapeAttr(o.keywords.join(', '))}">${o.keywords.map((k) => escapeHtml(keywordAbbrev(k))).join(' ')}</span>`
      : '';
    // RULE 715.3d: an Adventure creature exiled by its own spell half,
    // castable from here — flags it distinctly from an inert exiled card.
    const adventureBadge = o.adventure_castable
      ? `<span class="gf-adventure-badge" title="Abenteuer: aus dem Exil als Kreatur zauberbar">📖 Abenteuer</span>`
      : '';
    // RULE 722.3a: this permanent is prepared — its exiled prepare-spell
    // copy is castable (badged on that copy's own tile via `prepared_copy`
    // below, since that's a property of the copy, not of this permanent).
    const preparedBadge = o.prepared
      ? `<span class="gf-prepared-badge" title="Vorbereitet: die Zauberspruch-Kopie im Exil ist zauberbar">🛡️ Vorbereitet</span>`
      : '';
    // RULE 722.3c: this *is* that exiled prepare-spell copy.
    const preparedCopyBadge = o.prepared_copy
      ? `<span class="gf-prepared-badge" title="Vorbereitete Kopie: aus dem Exil zauberbar, solange die Quelle vorbereitet bleibt">🛡️ Kopie</span>`
      : '';
    const effectsSummary = effectSummaryHtml(o);
    return `
      <div class="gf-card-slot">
        <div class="${classes.join(' ')}" data-hover-card="${escapeHtml(o.name)}" title="${escapeHtml(o.name)}${pt}${o.tapped ? ' — getappt' : ''}">${inner}${attackBadge}${loyaltyBadge}${counterBadge}${keywordBadge}${adventureBadge}${preparedBadge}${preparedCopyBadge}${effectsSummary}</div>
        ${buttons}
      </div>`;
  }

  // Which exiled cards are castable from there right now, and why (RULE
  // 601.3b analogue / 715.3d / 722.3c) — the three independent mechanisms
  // `GameEngine._castable_from_exile`/`_has_temp_play_permission` check.
  // Returns ``null`` for an ordinary, inert exiled card.
  function exileCastableInfo(o, s) {
    if (o.adventure_castable) {
      return { reason: 'Adventure — eigene Zauberspruch-Hälfte bereits gecastet', duration: 'kein Zeitlimit (bis gezaubert)' };
    }
    if (o.prepared_copy) {
      return { reason: 'Vorbereitete Kopie (Regel 722.3c)', duration: 'solange die Quelle vorbereitet bleibt' };
    }
    const grantedTurn = s.temp_play_permissions ? s.temp_play_permissions[o.instance_id] : null;
    if (grantedTurn != null) {
      const source = s.temp_play_permission_source ? s.temp_play_permission_source[o.instance_id] : null;
      return {
        reason: source ? `Impulsiv gezogen von „${source}“` : 'Temporäre Spielerlaubnis',
        duration: `spielbar bis Ende von Zug ${grantedTurn + 1}`,
      };
    }
    return null;
  }

  // A "popup"-style zone next to the hand listing every exiled card that's
  // actually castable/playable right now (impulsive draw, Adventure,
  // Prepared) — the ordinary Exile zone still lists them too (this is a
  // prominent, additive callout, mirroring `libraryTopHtml`'s treatment of
  // a visible top-of-library card), each with why it's castable and how
  // long the permission lasts, since that's easy to lose track of buried in
  // a card's own oracle text once it's sitting in exile.
  function exileCastableHtml(p, s, byInstance, pending) {
    const entries = (p.exile || [])
      .map((o) => ({ o, info: exileCastableInfo(o, s) }))
      .filter(({ info }) => info !== null);
    if (!entries.length) return '';
    const imageCache = getState().imageCache;
    const cards = entries
      .map(({ o, info }) => `
        <div class="gf-exile-castable-entry">
          ${objCard(o, imageCache, pending ? [] : byInstance[o.instance_id] || [])}
          <p class="gf-exile-castable-caption">${escapeHtml(info.reason)}<br />${escapeHtml(info.duration)}</p>
        </div>`)
      .join('');
    return `
      <div class="gf-zone gf-exile-castable">
        <h4>🎇 Spielbar aus dem Exil (${entries.length})</h4>
        <div class="card-grid gf-exile-castable-list">${cards}</div>
      </div>`;
  }

  // The German label for a trace entry's `duration` (game/continuous.py):
  // how long the effect lasts, shown as a chip in the per-card summary.
  function durationLabel(d) {
    if (d === 'end_of_turn') return 'bis Zugende';
    if (d === 'permanent') return 'dauerhaft';
    return 'statisch'; // "static": lasts while its source stays in play
  }

  function durationTitle(d) {
    if (d === 'end_of_turn') return 'Bis zum Ende des Zuges (Regel 514.2)';
    if (d === 'permanent') return 'Dauerhaft (z. B. +1/+1-Marken, Regel 122)';
    return 'Solange die Quelle im Spiel bleibt (statischer Effekt, Regel 613)';
  }

  // Per-card "info point" (RULE 613): a Σ-badge that opens a breakdown of
  // every effect reshaping this permanent — Auren, Ausrüstung, Marken,
  // Anthem-/Bis-Zugende-Buffs — each with its source and duration, plus the
  // resulting characteristics (the "Summe"). Built from the object's
  // `static_trace`, so it only appears once something actually changed it.
  //
  // Uses the native Popover API (`popover` + `popovertarget`) so the panel
  // renders in the browser's top layer — never clipped by a card's/row's
  // `overflow` nor painted under a later card — and light-dismisses. It's
  // positioned at the badge by `wire()`'s `toggle` handler (the top layer
  // otherwise centres it).
  function effectSummaryHtml(o) {
    const trace = o.static_trace || [];
    if (!trace.length || o.instance_id == null) return '';
    const popId = `gf-eff-pop-${o.instance_id}`;
    const ptResult = o.power != null && o.toughness != null ? `${o.power}/${o.toughness}` : null;
    const keywords = (o.keywords || []).join(', ');
    const resultParts = [];
    if (ptResult) resultParts.push(`<strong>${escapeHtml(ptResult)}</strong>`);
    if (keywords) resultParts.push(escapeHtml(keywords));
    const rows = trace
      .map((t) => {
        const pt = t.power != null && t.toughness != null
          ? `<span class="gf-eff-pt">→ ${escapeHtml(`${t.power}/${t.toughness}`)}</span>`
          : '';
        return `<li>
          <span class="gf-eff-src">${escapeHtml(t.source)}</span>
          <span class="gf-eff-desc">${escapeHtml(t.description)}</span>${pt}
          <span class="gf-eff-dur gf-eff-dur--${escapeAttr(t.duration || 'static')}" title="${escapeAttr(durationTitle(t.duration))}">${escapeHtml(durationLabel(t.duration))}</span>
        </li>`;
      })
      .join('');
    return `<span class="gf-effects">
      <button type="button" class="gf-effects-badge" popovertarget="${escapeAttr(popId)}" title="Aktive Effekte &amp; Ergebnis anzeigen">Σ</button>
      <div id="${escapeAttr(popId)}" popover class="gf-effects-pop">
        <div class="gf-eff-result">Ergebnis: ${resultParts.join(' · ') || '—'}</div>
        <ul class="gf-eff-list">${rows}</ul>
      </div>
    </span>`;
  }

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

  // A card with a second castable face — a modal DFC's back (RULE 712.10),
  // a split card's other half (RULE 709.3), or an Adventure's spell half
  // (RULE 715.2b) — offers a second, independent action for the same hand
  // card; `faceHint` labels it with its own name so the two buttons are
  // distinguishable. Fuse (RULE 709.4) casts the same combined name shown
  // on the plain button, so it gets a short suffix instead of a redundant
  // repeated name. The front face keeps today's plain label (no visible
  // change for the common single-face case).
  function faceHint(a) {
    if (a.face === 'fuse') return ' (Fuse — beide Hälften)';
    return a.face ? ` — ${escapeHtml(a.name)}` : '';
  }

  // RULE 606: color-code a loyalty ability's button by its [+N]/[-N]/[0]
  // sign, so it reads at a glance distinctly from an ordinary activated
  // ability — the wire action only carries the pre-rendered cost_label
  // string (e.g. "[+2]"), not a raw signed int.
  const LOYALTY_COST_RE = /^\[([+-]?\d+)\]$/;
  function loyaltyModifierClass(costLabel) {
    const m = LOYALTY_COST_RE.exec(costLabel || '');
    if (!m) return '';
    const n = parseInt(m[1], 10);
    if (n > 0) return ' gf-card-action--loyalty-plus';
    if (n < 0) return ' gf-card-action--loyalty-minus';
    return ' gf-card-action--loyalty-zero';
  }

  // Kicker/Multikicker (RULE 702.33): a value input the same shape as an
  // {X} spell's `has_x`/`max_x` field — 0/1 for a plain Kicker, 0..N for
  // Multikicker (`a.max_kicker`); defaults to 0 (unkicked) rather than the
  // max, unlike X, since paying it is an optional cost increase the player
  // should opt into rather than pay by default.
  function kickerFieldHtml(a) {
    if (!a.has_kicker) return '';
    const title = a.kicker_cost ? `Kicker ${a.kicker_cost}` : 'Kicker';
    return `<input type="number" min="0" max="${a.max_kicker}" value="0" title="${escapeAttr(title)}" data-kicker-input="${kickerKey(a.instance_id, a.face)}" />`;
  }

  function cardActionButtons(cardActions) {
    if (!cardActions || !cardActions.length) return '';
    const buttons = [];
    for (const a of cardActions) {
      if (a.type === 'play_land') {
        buttons.push(
          actionButton(
            { type: 'play_land', instance_id: a.instance_id, name: a.name, face: a.face },
            `🌳 Land spielen${faceHint(a)}`
          )
        );
      } else if (a.type === 'cast_spell' && a.locked) {
        const reason = a.lock_reason || 'Kein gültiges Ziel';
        buttons.push(
          `<button type="button" class="gf-card-action gf-locked" disabled title="${escapeAttr(reason)}">🔒 ${escapeHtml(reason)}${faceHint(a)}</button>`
        );
      } else if (a.type === 'cast_spell' && a.requires_target) {
        buttons.push(castTargetHtml(a));
      } else if (a.type === 'cast_spell' && (a.has_x || a.has_kicker)) {
        const xField = a.has_x
          ? `<input type="number" min="0" max="${a.max_x}" value="${a.max_x}" data-x-input="${xKey(a.instance_id, a.face)}" />`
          : '';
        const suffix = [a.has_x ? 'X' : null, a.has_kicker ? 'Kicker' : null].filter(Boolean).join(', ');
        buttons.push(`
          <div class="gf-cast-x">
            ${xField}${kickerFieldHtml(a)}
            <button type="button" class="gf-card-action" data-cast-x='${escapeAttr(JSON.stringify({ iid: a.instance_id, face: a.face }))}'>✨ Zaubern (${suffix})${faceHint(a)}</button>
          </div>
        `);
      } else if (a.type === 'cast_spell') {
        const hint = a.base_cost && a.effective_cost && a.base_cost !== a.effective_cost
          ? ` 💰${escapeHtml(a.effective_cost)}`
          : '';
        buttons.push(
          actionButton(
            { type: 'cast_spell', instance_id: a.instance_id, name: a.name, face: a.face },
            `✨ Zaubern${hint}${faceHint(a)}`
          )
        );
      } else if (a.type === 'activate_ability' && a.locked) {
        const reason = a.lock_reason || 'Kein gültiges Ziel';
        buttons.push(
          `<button type="button" class="gf-card-action gf-locked" disabled title="${escapeAttr(reason)}">🔒 ${escapeHtml(reason)}</button>`
        );
      } else if (a.type === 'activate_ability' && a.requires_target) {
        buttons.push(castTargetHtml(a));
      } else if (a.type === 'activate_ability' && a.has_x) {
        buttons.push(`
          <div class="gf-cast-x">
            <input type="number" min="0" max="${a.max_x}" value="${a.max_x}" data-x-input="${a.instance_id}" />
            <button type="button" class="gf-card-action${loyaltyModifierClass(a.cost_label)}" data-activate-x='${escapeAttr(JSON.stringify({ iid: a.instance_id, ability_index: a.ability_index }))}'>⚡ ${escapeHtml(a.cost_label || 'Aktivieren')} (X)</button>
          </div>
        `);
      } else if (a.type === 'activate_ability' && a.tap_cost) {
        // Cost includes "tap N untapped <type>s you control" (RULE 602.1) —
        // which ones is the player's own choice, not an engine auto-pick.
        const startInfo = JSON.stringify({ iid: a.instance_id, type: 'activate_ability', ability_index: a.ability_index });
        buttons.push(
          `<button type="button" class="gf-card-action${loyaltyModifierClass(a.cost_label)}" data-tap-choice-start='${escapeAttr(startInfo)}'>⚡ ${escapeHtml(a.cost_label || 'Aktivieren')}</button>`
        );
      } else if (a.type === 'activate_ability') {
        buttons.push(
          actionButton(
            { type: 'activate_ability', instance_id: a.instance_id, ability_index: a.ability_index, name: a.name },
            `⚡ ${escapeHtml(a.cost_label || 'Aktivieren')}`,
            loyaltyModifierClass(a.cost_label)
          )
        );
      } else if (a.type === 'tap_for_mana') {
        const optsList = a.options || [{ index: 0, label: '⟳' }];
        // A mana ability whose cost is more than tapping itself (Selvala's
        // {G}, Gnarlroot Trapper's life payment, Birchlore Rangers' "tap two
        // other Elves") shows its full cost instead of a bare "Tappen".
        const extraCost = a.cost_label && a.cost_label !== '{T}';
        for (const opt of optsList) {
          const glyph = opt.label || '⟳';
          const text = extraCost
            ? `⟳ ${escapeHtml(a.cost_label)} → ${glyph}`
            : (optsList.length > 1 ? `⟳ ${glyph}` : `⟳ Tappen`);
          if (a.tap_cost) {
            // Which Elves pay the "tap N" part is the player's own choice
            // (RULE 602.1) — open the picker instead of sending right away.
            const startInfo = JSON.stringify({
              iid: a.instance_id, type: 'tap_for_mana',
              ability_index: a.ability_index, option_index: opt.index,
            });
            buttons.push(
              `<button type="button" class="gf-card-action" data-tap-choice-start='${escapeAttr(startInfo)}'>${text}</button>`
            );
          } else {
            buttons.push(
              actionButton(
                { type: 'tap_for_mana', instance_id: a.instance_id, option_index: opt.index, ability_index: a.ability_index },
                text
              )
            );
          }
        }
        // RULE 605.1a "any combination of colours" (Flamebraider/Gwenna/
        // Smokebraider/Selvala) — an additional split-across-colours option
        // alongside the single-colour buttons above (still legal, just less
        // flexible).
        if (a.any_combination) buttons.push(colorSplitHtml(a, 'tap_for_mana'));
      } else if (a.type === 'activate_hand_mana') {
        // RULE 605.1a "Exile this card from your hand: Add …" (Elvish/Simian
        // Spirit Guide) — the hand-zone counterpart of `tap_for_mana` above;
        // the cost is exiling the card itself, so there's no tap/summoning-
        // sickness framing to the button.
        const optsList = a.options || [{ index: 0, label: '⟳' }];
        for (const opt of optsList) {
          const glyph = opt.label || '⟳';
          const text = `📤 ${escapeHtml(a.cost_label || 'Exilieren')} → ${glyph}`;
          buttons.push(
            actionButton(
              { type: 'activate_hand_mana', instance_id: a.instance_id, option_index: opt.index, ability_index: a.ability_index },
              text
            )
          );
        }
        if (a.any_combination) buttons.push(colorSplitHtml(a, 'activate_hand_mana'));
      } else if (a.type === 'set_skip_untap') {
        // RULE 502.1 "you may choose not to untap ~ during your untap step"
        // (Rubinia Soulsinger/Hivis of the Scale/The Pandorica-shaped) — a
        // sticky preference toggle (`GameObject.skip_untap`), not a one-off
        // action, so the button just flips it and reflects the current state.
        const on = a.skip_untap;
        buttons.push(
          actionButton(
            { type: 'set_skip_untap', instance_id: a.instance_id, value: !on },
            on ? '🔓 Wieder normal enttappen' : '🔒 Nicht enttappen lassen',
            on ? ' gf-card-action--skip-untap-on' : ''
          )
        );
      } else if (a.type === 'attack') {
        buttons.push(attackControlHtml(a));
      }
    }
    return buttons.length ? `<div class="gf-card-actions">${buttons.join('')}</div>` : '';
  }

  // RULE 605.1a "any combination of colours" split builder: one number input
  // per real color (never colorless — RULE 605.1a's "any color" excludes it,
  // `mana_abilities._ALL_COLORS`), constrained client-side to sum to exactly
  // `combination_total` before the confirm button sends `color_split`
  // (`kind` picks which action type the confirm dispatches — the shape is
  // otherwise identical for a battlefield `tap_for_mana` ability and a
  // hand-zone `activate_hand_mana` one).
  function colorSplitHtml(a, kind) {
    const colors = ['W', 'U', 'B', 'R', 'G'];
    const glyph = { W: '⚪', U: '🔵', B: '⚫', R: '🔴', G: '🟢' };
    const inputs = colors
      .map(
        (c) =>
          `<label class="gf-split-color" title="${c}">${glyph[c]}<input type="number" min="0" max="${a.combination_total}" value="0" data-split-color="${c}" /></label>`
      )
      .join('');
    const actionInfo = JSON.stringify({ type: kind, instance_id: a.instance_id, ability_index: a.ability_index });
    return `
      <div class="gf-mana-split" data-split-total="${a.combination_total}" data-split-action='${escapeAttr(actionInfo)}'>
        <span class="gf-split-hint">Farbkombination (${a.combination_total}):</span>
        ${inputs}
        <button type="button" class="gf-card-action" data-split-confirm>💎 Erzeugen</button>
      </div>`;
  }

  function castTargetHtml(a) {
    const iid = a.instance_id;
    const xField = a.has_x
      ? `<input type="number" min="0" max="${a.max_x}" value="${a.max_x}" data-x-input="${xKey(iid, a.face)}" />`
      : '';
    const startInfo = JSON.stringify({ iid, type: a.type, ability_index: a.ability_index, face: a.face });
    const label = a.type === 'activate_ability'
      ? `⚡ ${escapeHtml(a.cost_label || 'Aktivieren')} → Ziel ▾`
      : `✨ Zaubern → Ziel ▾${faceHint(a)}`;
    const lc = a.type === 'activate_ability' ? loyaltyModifierClass(a.cost_label) : '';
    return `<div class="gf-cast-targets">${xField}${kickerFieldHtml(a)}<button type="button" class="gf-card-action${lc}" data-cast-target-start='${escapeAttr(startInfo)}'>${label}</button></div>`;
  }

  function castTargetModalHtml() {
    if (!castTargeting) return '';
    const iid = castTargeting.instanceId;
    const total = castTargeting.requirements.length;
    const idx = castTargeting.reqIndex;
    const req = castTargeting.requirements[idx] || {};
    let options = req.options || [];
    if (castTargeting.excludePicked) {
      // A "tap N untapped <type>s you control" cost (RULE 602.1): the same
      // permanent can't pay two of the N picks.
      const pickedIds = new Set(castTargeting.targets.map((t) => t.instance_id));
      options = options.filter((o) => !pickedIds.has(o.instance_id));
    }
    if (castTargeting.excludeControllers) {
      // Run Away Together/Protector of the Wastes-shaped "controlled by
      // different players": once one round has picked a permanent, no
      // later round may pick another one sharing that controller.
      const pickedControllers = new Set((castTargeting.pickedControllers || []).filter((c) => c != null));
      options = options.filter((o) => !pickedControllers.has(o.controller_id));
    }
    const buttons = options.map((o) => {
      const payload = JSON.stringify({
        instance_id: iid, target: targetOptionPayload(o), controller_id: o.controller_id ?? null,
      });
      const hover = o.instance_id != null ? ` data-hover-card="${escapeHtml(o.name || '')}"` : '';
      const glyph = castTargeting.isTapChoice ? '⟳' : '🎯';
      return `<button type="button"${hover} data-cast-target-pick='${escapeAttr(payload)}'>${glyph} ${escapeHtml(o.name)}</button>`;
    });
    if (req.optional) {
      const skip = JSON.stringify({ instance_id: iid, target: null });
      buttons.push(`<button type="button" class="gf-decline" data-cast-target-pick='${escapeAttr(skip)}'>∅ Kein Ziel</button>`);
    }
    const heading = castTargeting.isTapChoice ? 'Kosten bezahlen' : 'Ziel wählen';
    const progress = total > 1 ? `${idx + 1} von ${total}` : (castTargeting.isTapChoice ? 'Auswählen' : 'Ziel wählen');
    return `
      <div class="gf-modal-overlay">
        <div class="gf-modal gf-target-modal" role="dialog" aria-modal="true">
          <div class="gf-modal-head">
            <span class="gf-modal-icon">${castTargeting.isTapChoice ? '⟳' : '🎯'}</span>
            <div>
              <h4>${heading}: ${escapeHtml(req.label || '')}</h4>
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

  function targetOptionPayload(o) {
    return o.player_id != null ? { player_id: o.player_id } : { instance_id: o.instance_id };
  }

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

  function defenderPayload(d) {
    return d.kind === 'planeswalker'
      ? { kind: 'planeswalker', instance_id: d.instance_id }
      : { kind: 'player', id: d.id };
  }

  function actionButton(action, label, extraClass = '') {
    return `<button type="button" class="gf-card-action${extraClass}" data-action='${escapeAttr(JSON.stringify(action))}'>${label}</button>`;
  }

  // The passive "goldfish" opponent: a compact strip with its life (the
  // thing you're racing down), plus hidden hand/graveyard/library counts.
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

  function gameOverHtml(s, me) {
    return `
      <div class="gf-gameover">
        ${gameResultBanner(s, me)}
      </div>`;
  }

  function gameResultBanner(s, me) {
    const winner = s.winner_id
      ? s.players.find((p) => p.id === s.winner_id)
      : null;
    const youWon = winner && me && winner.id === me.id;
    const banner = winner
      ? youWon
        ? '🏆 Gewonnen.'
        : `Verloren – Sieger: ${escapeHtml(winner.name)}.`
      : 'Spiel beendet.';
    return `<p class="server-status ${youWon ? 'ok' : 'warning'}">${banner}</p>`;
  }

  function manaPoolHtml(pool) {
    const order = ['W', 'U', 'B', 'R', 'G', 'C'];
    const glyph = { W: '⚪', U: '🔵', B: '⚫', R: '🔴', G: '🟢', C: '⟡' };
    const parts = order.filter((c) => pool[c] > 0).map((c) => `<span class="gf-mana">${glyph[c]}${pool[c]}</span>`);
    const restrictedParts = restrictedManaHtml(pool.restricted, glyph, order);
    const empty = !parts.length && !restrictedParts.length;
    return `<div class="gf-manapool" title="Mana-Pool">${empty ? '<span class="empty-state">kein Mana</span>' : parts.join('') + restrictedParts.join('')}</div>`;
  }

  // RULE 605.3a: mana tagged "spend only on X" (`ManaPool.to_dict`'s additive
  // `restricted` key — a list of lots, never merged with the ordinary WUBRGC
  // counts above) shown as its own badge per lot, so a player can tell
  // restricted floating mana apart from ordinary mana instead of it just
  // silently failing to pay an unrelated cost later.
  function restrictedManaHtml(restricted, glyph, order) {
    if (!restricted || !restricted.length) return [];
    return restricted.map((lot) => {
      const amounts = order
        .filter((c) => c !== 'C' && lot.amounts[c] > 0)
        .concat(lot.amounts.C > 0 ? ['C'] : [])
        .map((c) => `${glyph[c]}${lot.amounts[c]}`)
        .join('');
      return `<span class="gf-mana gf-mana-restricted" title="Zweckgebunden: ${escapeAttr(restrictionLabel(lot.restriction))}">🔒${amounts}</span>`;
    });
  }

  // Human label for an opaque restriction dict (`game/mana_abilities.py`'s
  // `_parse_restriction` whitelist — this module has no server-side label
  // string to read, unlike `TargetSpec.label()` for targets, so the mapping
  // lives here).
  function restrictionLabel(restriction) {
    const kind = restriction?.kind;
    if (kind === 'contains_x') return 'nur für Zaubersprüche mit {X} in den Kosten';
    if (kind === 'creature_spell') {
      return restriction.allow_ability
        ? 'nur um einen Kreaturenzauber zu wirken oder eine Fähigkeit zu aktivieren'
        : 'nur um einen Kreaturenzauber zu wirken';
    }
    if (kind === 'commander_spell') return 'nur für deinen Commander';
    if (kind === 'legendary_spell') return 'nur für legendäre Zaubersprüche';
    if (kind === 'instant_or_sorcery_spell') return 'nur für Spontanzauber/Hexereien';
    if (kind === 'type_spell') {
      const types = (restriction.types || []).join('/');
      return restriction.allow_ability
        ? `nur für ${types}-Zaubersprüche/-Fähigkeiten`
        : `nur für ${types}-Zaubersprüche`;
    }
    return 'zweckgebunden';
  }

  function moveLogHtml(log) {
    if (!log || !log.length) return '';
    const recent = log.slice(-8);
    return `<div class="gf-movelog"><h4>Verlauf</h4><ol>${recent.map((m) => `<li>${escapeHtml(m)}</li>`).join('')}</ol></div>`;
  }

  // The optional static-effects panel (RULE 613): (1) every active static
  // ability in play and (2) the layer-by-layer derivation of each permanent
  // whose characteristics a static effect changed.
  // RULE 603.7's "planned" delayed triggered abilities — armed by a
  // resolved spell/ability but not yet fired ("at the beginning of your
  // next upkeep/the next end step, …", Ephemerate's Rebound/Marchesa, the
  // Black Rose's counter-death return/Sneak Attack's delayed sacrifice-
  // shaped). Always shown (no toggle, unlike the static-effects panel)
  // when non-empty — same "surface it, don't hide it behind an opt-in"
  // treatment the Stack overlay gets, just not modal since nothing here
  // needs a response right now.
  function delayedTriggersPanelHtml(view) {
    const dts = view.delayed_triggers || [];
    if (!dts.length) return '';
    const imageCache = getState().imageCache;
    const items = dts
      .map((dt) => {
        const visual = dt.source;
        const imageUrl = visual ? resolveImageUrl(visual, imageCache) : null;
        const thumb = imageUrl
          ? `<img src="${imageUrl}" alt="${escapeHtml(visual.name)}" loading="lazy" />`
          : '<span class="gf-delayed-noart">⏳</span>';
        const hover = visual ? ` data-hover-card="${escapeHtml(visual.name)}"` : '';
        const label = dt.description || (visual ? visual.name : 'Ausgelöste Fähigkeit');
        return `
          <li class="gf-delayed-item">
            <div class="gf-delayed-thumb"${hover}>${thumb}</div>
            <div class="gf-delayed-body">
              <p class="gf-delayed-desc">${escapeHtml(label)}</p>
              <p class="gf-delayed-when">⏳ ${escapeHtml(delayedTriggerWhenLabel(dt))}</p>
            </div>
          </li>`;
      })
      .join('');
    return `
      <div class="gf-delayed-panel">
        <h4>⏳ Geplant (Regel 603.7)</h4>
        <ul class="gf-delayed-list">${items}</ul>
      </div>`;
  }

  // "Zu Beginn von <Spieler>s nächstem Schritt …" (scope "controller",
  // e.g. Ephemerate's Rebound/Mana Drain) vs. "Zu Beginn des nächsten
  // Schritts …" (scope "any" — the very next matching step regardless of
  // whose turn, e.g. Marchesa's/Sneak Attack's "next end step"). Phrased
  // via the gender-neutral "Schritt „X“" rather than declining the step
  // name's own noun (Versorgung/Ende/Hauptphase don't all share a gender).
  function delayedTriggerWhenLabel(dt) {
    const stepLabel = STEP_LABELS[dt.step] || dt.step || '—';
    if (dt.scope === 'any') {
      return `Zu Beginn des nächsten Schritts „${stepLabel}“`;
    }
    return `Zu Beginn von ${playerName(dt.controller_id)}s nächstem Schritt „${stepLabel}“`;
  }

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

  function collectCostReductions(actions) {
    return actions
      .filter((a) => a.type === 'cast_spell' && a.base_cost && a.effective_cost && a.base_cost !== a.effective_cost)
      .map((a) => ({ name: a.name, base: a.base_cost, effective: a.effective_cost }));
  }

  function statusHtml() {
    if (!status) return '';
    return `<p class="server-status ${statusKind}">${escapeHtml(status)}</p>`;
  }

  function lifeBox(label, life) {
    return `<div class="gf-life"><span class="gf-life-label">${escapeHtml(label)}</span><span class="life-total">${life}</span></div>`;
  }

  return { mount, start, refresh, setAssets };
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str == null ? '' : String(str);
  return div.innerHTML;
}

function escapeAttr(str) {
  return String(str).replace(/'/g, '&#39;').replace(/"/g, '&quot;');
}
