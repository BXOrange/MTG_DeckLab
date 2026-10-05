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
import { sendGameAction, rewindGame, cardImageUrl, saveUiDraft, GENERIC_TOKEN_KEY } from './api.js';
import { getCookie, setCookie } from './cookies.js';
import { getBoardScale, onBoardScaleChange } from './boardScale.js';
import { bannerColorLabel, bannerStyle } from './bannerColors.js';
import { MANA_SYMBOL_EMOJI } from './cardTile.js';
import {
  getBotSpeedMs,
  getShowOpponentHand,
  getCompactView,
  getStopsPref,
  setStopsPref,
  saveSettings,
} from './settings.js';
import { t, tPlural } from './i18n.js';
import { setHeaderMessage } from './headerMessage.js';

const TABLE_EMOTES = ['👍', '👏', 'GG', '🤔', '⏳']; // Server-approved table reactions.
const CHAT_BOTTOM_THRESHOLD_PX = 24; // Keep reading position unless near the newest message.

const PHASE_LABELS = {
  beginning: t('bd.phase.beginning'),
  precombat_main: t('bd.phase.precombat_main'),
  combat: t('bd.phase.combat'),
  postcombat_main: t('bd.phase.postcombat_main'),
  ending: t('bd.phase.ending'),
};
const STEP_LABELS = {
  untap: t('bd.step.untap'),
  upkeep: t('bd.step.upkeep'),
  draw: t('bd.step.draw'),
  main1: t('bd.step.main1'),
  begin_combat: t('bd.step.begin_combat'),
  declare_attackers: t('bd.step.declare_attackers'),
  declare_blockers: t('bd.step.declare_blockers'),
  combat_damage: t('bd.step.combat_damage'),
  end_combat: t('bd.step.end_combat'),
  main2: t('bd.step.main2'),
  end: t('bd.step.end'),
  cleanup: t('bd.step.cleanup'),
  // Not a real step name on its own — `DelayedTrigger.step` uses this for
  // "your next main phase" (Mana Drain-shaped), matching whichever of
  // main1/main2 begins first (`GameEngine._fire_delayed_triggers`).
  main: t('bd.step.main'),
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
  land_tapped: '💧', land_tapped_reveal: '💧', order_triggers: '🔀', trigger_target: '🎯',
  enter_as_copy: '🪞', counter_unless_pays: '🚫', ward: '🛡️', trigger_doubler_tap: '🔁',
  commander_zone: '👑', trigger_mode: '🎭', add_mana_any_color: '💎',
  choose_creature_type: '🐾', choose_color: '🎨', choose_basic_land_type: '🗺️', read_ahead: '📜',
  scry: '🔮', reorder_top: '🔮', look_hand: '👁️', surveil: '🕵️', clash: '⚔️', opening_hand_battlefield: '🌅', dredge: '⚰️',
  explore_bin: '🧭', populate: '🌱', bolster: '💪', blight: '🥀', endure: '🕊️', recruit: '🎖️',
  // MEC-108: "your choice of a flying counter or a lifelink counter" — at resolution / as it enters.
  counter_kind: '🏷️', choose_enter_counter: '🏷️',
  // Explorer's Scope's "look at the top card, if it's a land you may put
  // it onto the battlefield tapped" (bug report, 2026-09-04).
  peek_top_land: '🔭',
  // RULE 701.38 vote / RULE 701.55 villainous choice (MEC-46 / ENG-33).
  vote: '🗳️', vote_object: '🗳️', villainous_choice: '😈',
  // RULE 720 / Word of Command — pick a card from the target's hand (MEC-51b).
  word_of_command: '🗣️',
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
 * @param {{sendAction?: Function, rewind?: Function}} [opts.transport] How
 *   actions reach the server. Defaults to the REST session API (`api.js`'s
 *   `sendGameAction`/`rewindGame`), which is right for every solo mode;
 *   multiplayer swaps in its own so each action is attributed to a seat
 *   (`POST /api/multiplayer/games/{id}/action`) and so the pushed view from
 *   the lobby socket, not the HTTP reply, is what repaints the board.
 * @param {boolean} [opts.allowRewind=true] Whether "Zurücknehmen" is offered.
 *   Off for multiplayer: undo is a solo-practice affordance, and one player
 *   can't unilaterally rewind a shared game.
 * @param {boolean} [opts.allowFastForward=true] Whether "Nächste
 *   Entscheidung" is offered. Off for multiplayer, where skipping steps
 *   would skip *the opponent's* response windows too.
 * @param {(playerId: string) => ({connected?: boolean, banner_color?: string|null}|null)} [opts.seatStatus]
 *   Out-of-game facts about a seat, drawn on that player's board. Only
 *   multiplayer supplies it (both of these live in the lobby, not in the
 *   `GameState`): `connected` badges a player who dropped as visibly
 *   *absent* rather than just mysteriously never doing anything, and
 *   `banner_color` is the colours they picked in Setup for their own title
 *   bar (`bannerColors.js`, `services/lobby.py`'s `Seat.banner_color`).
 *   Without it — every solo mode — banners stay the plain felt header.
 */
export function createGameBoardView(opts = {}) {
  const onViewChange = opts.onViewChange || (() => {});
  const extraControlsFn = opts.extraControls || (() => []);
  const transport = opts.transport || {};
  const seatStatus = opts.seatStatus || (() => null);
  const allowRewind = opts.allowRewind !== false;
  const allowFastForward = opts.allowFastForward !== false;

  let root = null;
  let sessionId = null;
  let view = null;
  let latestByInstance = {};
  let dragSource = null;
  let dragHandlersInstalled = false;
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
  let compactView = getCompactView();
  // Optional, default-hidden "static effects / layer trace" panel (RULE 613).
  let showStatics = getCookie('gf_show_statics') === '1';
  // Play-area layout: the static-zone column (command/library/graveyard/
  // exile) sits on one side, battlefield+hand on the other; toggleable side.
  let zonesLeft = getCookie('gf_zones_side') === 'left';
  // The same choice, but for the pod grid (3+ boards, see `podGrid`), where
  // a fixed "left"/"right" would put one column's zones against the screen
  // edge and the other's in the middle. There the two columns mirror each
  // other instead, so the setting is *inside* (both zone columns meet in the
  // middle) or *outside* (they hug the outer edges and the battlefields face
  // each other). Outside by default: that's the physical table it models —
  // your library and graveyard sit at your own edge, the boards meet in the
  // middle — and it puts the two things you compare next to each other.
  // Persisted separately from `zonesLeft` because they mean different things
  // and a player wants both remembered.
  let zonesInside = getCookie('gf_zones_pod') === 'inside';
  //: Below this the pod grid's two columns are narrower than they are
  //: useful, so it falls back to the stacked layout (and the zone toggle
  //: back to plain left/right — `zonesSideFor`). A *viewport* query rather
  //: than a container one: the app's sidebar eats some of the width too,
  //: and it can be collapsed away. main.css deliberately has no matching
  //: media query — this is the only place the breakpoint lives.
  const POD_GRID_MIN_WIDTH = 1200;
  const podGridMedia = window.matchMedia?.(`(min-width: ${POD_GRID_MIN_WIDTH}px)`) || null;
  //: Crossing the breakpoint changes the layout *and* what the toggle
  //: means, so it has to repaint. No teardown: a board view lives as long
  //: as its controller, which lives as long as the page.
  podGridMedia?.addEventListener('change', () => render());
  // Whole-board zoom (`boardScale.js`) is one app-wide preference — its
  // control sits at the bottom of the sidebar (`app.js`), not in this
  // board's own rail — so every instance just repaints when it changes.
  // Same no-teardown reasoning as `podGridMedia` above.
  onBoardScaleChange(() => render());
  window.addEventListener('compact-view-changed', () => {
    compactView = getCompactView();
    render();
  });
  // The stack lives in the left rail now (`railStackHtml`) — always visible,
  // never overlaying the board, so there is nothing to "push aside" any more.
  // Entries that have just resolved linger for a moment as greyed-out ghosts
  // (`resolvedGhosts`) so it stays briefly visible what went on the stack,
  // even in the solo modes where the engine auto-drains it.
  let resolvedGhosts = [];
  const GHOST_LIFETIME_MS = 2200;
  const GHOST_MAX_ITEMS = 4;
  // A pending-choice popup (search/scry/surveil/ward/…) overlays the board
  // the same way; same "push aside" escape hatch, e.g. to check the
  // graveyard or a permanent's text before answering.
  let choiceAside = false;
  // Attacking creatures whose "choose a defender" submenu is open (2+ legal
  // defenders, RULE 508.1a).
  const attackMenuOpen = new Set();
  // Opponents whose board is folded away to just its header. Only offered at
  // a table of 3+ (`services/lobby.py` opens up to four seats): three full
  // opponent boards stacked above your own is a lot of scrolling, and most
  // of the time only one of them is the one you're thinking about. Purely a
  // client-side view state — nothing about the game changes, and an
  // opponent's hidden zones were never on the wire to begin with (RULE
  // 400.2). Starts empty, so nothing is hidden unless asked for.
  const collapsedBoards = new Set();
  // Friedhof / Exil zone bodies the player has expanded. Both zones are
  // collapsed to just their header by default so a full graveyard (60+
  // entries) can't stretch the fixed-width side column and push the rest of
  // the board around — clicking the header toggles the list open, and the
  // open list is height-capped and scrolls inside itself. Keyed
  // `${playerId}:graveyard` / `${playerId}:exile`; purely a client-side
  // view state, same shape as `collapsedBoards`.
  const expandedZones = new Set();
  // Double-faced permanents a player has clicked "🔄" on to *preview* the
  // other face — purely a client-side view toggle (RULE 712 has no such
  // concept; the object's real `transformed` state is untouched), so a
  // player can check a flip-card's back before it actually transforms, or
  // just look at the back of an already-transformed one. Keyed by
  // instance_id, same shape as `attackMenuOpen`.
  const flippedForView = new Set();
  // RULE 115/601.2c: which battlefield permanents are currently the target
  // of something on the stack, and which of those form a *mutual* pair — two
  // permanents each targeting the other (e.g. two Fight-shaped abilities, or
  // two removal spells that happen to name each other's source). Recomputed
  // every `render()` from `s.stack` (each item's already-chosen `targets`,
  // `StackItem.to_dict()` in `models/game_state.py`) rather than stored —
  // it's derived, view-only state, same footing as `flippedForView` above.
  let targetedInstanceIds = new Set();
  let mutualTargetPairIds = new Set();
  let abilitySourceInstanceIds = new Set();

  function updateTargetOverlays(s) {
    targetedInstanceIds = new Set();
    const edges = new Map(); // sourceInstanceId -> Set(targetInstanceId)
    for (const item of s.stack || []) {
      for (const tgt of item.targets || []) {
        if (tgt.instance_id != null) targetedInstanceIds.add(tgt.instance_id);
      }
      // The permanent "doing" the targeting: an ability's own source, or a
      // spell's own object (only meaningful once it's a permanent already on
      // the battlefield — e.g. an activated/triggered ability off a
      // creature; a spell still on the stack isn't a permanent yet, so it
      // can't be the *other* half of a mutual pair on the battlefield).
      const sourceId = item.source ? item.source.instance_id : null;
      if (sourceId == null) continue;
      for (const tgt of item.targets || []) {
        if (tgt.instance_id == null || tgt.instance_id === sourceId) continue;
        if (!edges.has(sourceId)) edges.set(sourceId, new Set());
        edges.get(sourceId).add(tgt.instance_id);
      }
    }
    const mutual = new Set();
    for (const [a, targets] of edges) {
      for (const b of targets) {
        if (edges.get(b)?.has(a)) {
          mutual.add(a);
          mutual.add(b);
        }
      }
    }
    mutualTargetPairIds = mutual;
  }

  // Highlight the permanent that owns an ability currently waiting on the
  // stack or on an interactive choice. The source is derived from the stack
  // so the mark also survives while the ability has paused on a choice.
  function updateAbilitySourceOverlays(s, pending) {
    const sourceIds = new Set();
    for (const item of s.stack || []) {
      if (item.kind !== 'ability') continue;
      const sourceId = item.source?.instance_id;
      if (sourceId != null) sourceIds.add(sourceId);
    }
    for (const key of ['source_instance_id', 'source_id', 'explorer_id', 'permanent_id']) {
      const sourceId = pending?.[key];
      if (sourceId != null) sourceIds.add(sourceId);
    }
    abilitySourceInstanceIds = sourceIds;
  }
  // --- "Time to react" countdown (RULE 117, interactive-priority sessions) ---
  // This is a *response* clock, not a turn clock: it always runs while this
  // client holds priority **on another player's turn**, and on your **own**
  // turn it runs only in the windows where you're genuinely just watching —
  // something on the stack to respond to, or the passive upkeep/draw/end
  // steps (`reactTimerSuppressedHere`). It stays out of your own main
  // phases and combat, where you're the one developing the board/attacking
  // (RULE 117) and a half-finished turn must not tick away under you; a
  // genuinely absent active player is the server idle-timeout's job
  // (`MTG_MULTIPLAYER_IDLE_TIMEOUT`), not this. When it does run, the left
  // rail shows a shrinking progress bar and the remaining seconds; at zero
  // it passes for you. It is deliberately *not* silent, and any interaction
  // with the board — or the explicit "interrupt" button — cancels it for
  // that window. The number of seconds is a server setting
  // (`view.priority.timer_seconds`, `config.MULTIPLAYER_SPELL_TIMER_SECONDS`,
  // per-table overridable); 0 turns the countdown off entirely (manual
  // passing only).
  let autoPassSeconds = 0;
  let autoPassTimer = null;
  let autoPassRemaining = 0;
  //: Set once the player touches the board during a priority window; the
  //: countdown doesn't restart until they next *gain* priority.
  let autoPassCancelled = false;
  //: Which priority window the current countdown belongs to, so a repaint
  //: that doesn't change whose turn it is doesn't restart the clock.
  let autoPassWindowKey = null;

  // --- Auto-skip empty priority windows ---------------------------------
  //: A priority window that offers *nothing but* `pass_priority` is passed
  //: straight through, unconditionally — no countdown, since there is by
  //: definition nothing to interrupt, and it chains through consecutive
  //: empty windows one render at a time (`skipEmptyArmed`/`syncAutoPass`).
  //: The priority window a skip was already *attempted* for
  //: (`priorityWindowKey()`) — the multiplayer transport intentionally
  //: returns no fresh `data` from `act()` (see multiplayerView.js: it
  //: waits for the socket push instead, so it never paints a reply that's
  //: already stale by the time it arrives), so `view` — and therefore this
  //: window's key — can stay exactly as it was across several renders
  //: while the real pass is still in flight to the server and back over
  //: the socket. Without this guard, every one of those renders would see
  //: the *same* "nothing to do here" window and fire another
  //: `pass_priority`, as fast as the JS event loop allows, instead of
  //: firing once and then genuinely waiting — which is what made casting
  //: feel "impossible": the resulting flood of redundant (and, once the
  //: real pass lands server-side, failing) requests kept re-rendering the
  //: board out from under a click before it could register.
  let skipAttemptedForKey = null;

  /** Whether this client currently has a choice worth stopping for. */
  function hasMeaningfulAction() {
    return (view?.legal_actions || []).some((a) => a.type !== 'pass_priority');
  }

  /**
   * Whether a priority window with *nothing to do* should be passed straight
   * through right now. Always on for an interactive session (there is by
   * definition nothing to interrupt), so the countdown bar only ever runs on
   * a window where the player actually has a choice.
   */
  function skipEmptyArmed() {
    if (!interactivePriority() || !hasPriority()) return false;
    const s = view.state;
    if (s.game_over || s.pending_choice || busy) return false;
    return !hasMeaningfulAction();
  }

  //: On your own turn with an empty stack, the countdown still runs in
  //: these passive steps — upkeep, draw and the end step, where you're
  //: mostly just watching for a reason to act rather than developing the
  //: board. (Untap/cleanup give nobody priority — RULE 117.3a — so they
  //: never reach this check at all.)
  const OWN_TURN_TIMER_STEPS = new Set(['upkeep', 'draw', 'end']);

  /**
   * Whether the "time to react" countdown should be silent for the window
   * this client currently holds. Never on another player's turn. On your
   * **own** turn it's suppressed unless there's something on the stack to
   * respond to, or the current step is one of `OWN_TURN_TIMER_STEPS` — your
   * main phases and combat always suppress it (RULE 117: you're the one
   * acting there, not reacting).
   */
  function reactTimerSuppressedHere() {
    const mine = actingSeat();
    const s = view?.state;
    if (!mine || !s || s.active_player_id !== mine) return false;
    if (s.stack && s.stack.length > 0) return false;
    return !OWN_TURN_TIMER_STEPS.has(s.current_step);
  }

  /** Whether the countdown should be running right now. */
  function autoPassArmed() {
    if (autoPassCancelled || autoPassSeconds <= 0) return false;
    if (!interactivePriority() || !hasPriority()) return false;
    const s = view.state;
    if (s.game_over || s.pending_choice || busy) return false;
    if (reactTimerSuppressedHere()) return false;
    return true;
  }

  // --- "Pass this turn" / "Skip to end step" (VIS-12) -----------------------
  //: A one-shot *yield* lives on the server (`GameSession._yields`, shown to
  //: everyone as `view.priority.yields`): "Pass this turn" (an opponent's
  //: turn) has the server pass this seat's priority windows until that turn
  //: ends, "Skip to end step" (your own turn) up to the end step; either
  //: stops passing the moment another player has a spell or ability on
  //: the stack to respond to. Nothing is armed client-side any more, so a
  //: reload, a second tab and a Solo bot's reply all see the same state.
  //: Whether this session's saved stops were already offered to the server
  //: (reset per game), and whether the rail's stops panel is expanded.
  let stopsSynced = false;
  let stopsPanelOpen = false;

  /** The yield this seat has armed (`turn`/`end_step`), or null. */
  function myYield() {
    const seat = actingSeat();
    return (seat && view?.priority?.yields?.[seat]) || null;
  }

  /** A key identifying the current priority window (see `autoPassWindowKey`). */
  function priorityWindowKey() {
    const s = view?.state;
    if (!s) return null;
    return [
      s.internal_turn.number,
      s.current_step,
      view.priority?.player_id,
      (view.priority?.passed || []).join(','),
      s.stack.length,
    ].join('|');
  }

  function stopAutoPass() {
    if (autoPassTimer !== null) {
      clearInterval(autoPassTimer);
      autoPassTimer = null;
    }
  }

  /** The per-priority countdown length from the server (0 = off). */
  function serverTimerSeconds() {
    const n = Number(view?.priority?.timer_seconds);
    return Number.isFinite(n) && n > 0 ? Math.round(n) : 0;
  }

  /** (Re)start the countdown if this is a new window and it's armed. */
  function syncAutoPass() {
    syncStopsPref();
    // The countdown length is a server setting (per-table overridable);
    // pick it up fresh from every view.
    autoPassSeconds = serverTimerSeconds();
    const windowKey = priorityWindowKey();
    // Skipping wins over the countdown — a window with no options at all
    // shouldn't cost anyone three seconds of watching a timer. Fired at
    // most once per window (`skipAttemptedForKey`) — see that field's
    // comment for why a second, third, … attempt against an unchanged
    // window is a bug, not extra safety.
    if (skipEmptyArmed() && windowKey !== skipAttemptedForKey) {
      skipAttemptedForKey = windowKey;
      stopAutoPass();
      act({ type: 'pass_priority' });
      return;
    }
    const key = windowKey;
    if (key !== autoPassWindowKey) {
      autoPassWindowKey = key;
      autoPassCancelled = false; // a new window is a fresh decision
      stopAutoPass();
    }
    if (!autoPassArmed()) {
      stopAutoPass();
      return;
    }
    if (autoPassTimer !== null) return; // already counting down this window
    autoPassRemaining = autoPassSeconds;
    paintCountdown();
    autoPassTimer = setInterval(() => {
      autoPassRemaining -= 1;
      paintCountdown();
      if (autoPassRemaining > 0) return;
      stopAutoPass();
      // Re-check on fire: a lot can have happened in three seconds.
      if (autoPassArmed()) act({ type: 'pass_priority' });
    }, 1000);
  }

  // Repaint just the number + the shrinking bar, not the board — a full
  // re-render every second would tear down and rebuild every card tile under
  // the player's cursor.
  function paintCountdown() {
    const remaining = Math.max(0, autoPassRemaining);
    root?.querySelectorAll('[data-timer-count]').forEach((el) => {
      el.textContent = String(remaining);
    });
    const frac = autoPassSeconds > 0 ? remaining / autoPassSeconds : 0;
    root?.querySelectorAll('[data-timer-bar]').forEach((el) => {
      el.style.setProperty('--gf-timer-frac', String(frac));
    });
  }

  /** The player is doing something — don't pass out from under them. */
  function cancelAutoPassForThisWindow() {
    if (autoPassTimer === null && !autoPassCancelled) return;
    autoPassCancelled = true;
    stopAutoPass();
    root?.querySelector('.gf-rail-timer')?.classList.add('gf-timer-off');
  }

  // A block being assembled (RULE 509.1a), `blockerInstanceId -> attackerId`.
  // Collected client-side and submitted as *one* `declare_blockers` action,
  // because the menace family (RULE 702.111b, "…can't be blocked except by
  // N or more creatures") is validated across the whole assignment — a
  // blocker-at-a-time submission could never satisfy it.
  let blockDraft = new Map();
  // A targeting spell/ability (RULE 115) mid-cast: `{ instanceId, requirements,
  // reqIndex, targets: [], x, send }` or null. See `castTargetHtml`.
  let castTargeting = null;
  // PLR-6: `move_log.length` (+ session id) from the last view `blockDraft`/
  // `castTargeting` were invalidated against, so `applyView` can tell "a
  // real move happened, these may no longer be valid" apart from "a view
  // merely arrived" (e.g. another player's socket reconnecting rebroadcasts
  // the *same* committed position to the whole table) — only the former
  // should wipe an in-progress draft. `null` means "not established yet",
  // which always counts as changed (a fresh `start()`).
  let lastDraftMoveLogLen = null;
  let lastDraftSessionId = null;
  // VIS-7: how long to wait between revealing consecutive new rail-stack
  // ghosts from the same view (almost always a bot's whole batched turn —
  // see `run_bots`/`_after_move` in api/multiplayer.py, which answer a bot
  // to completion before ever broadcasting) — 0 reproduces the old
  // "all at once" behaviour. Adjustable live in Settings.
  let botSpeedMs = getBotSpeedMs();
  window.addEventListener('bot-speed-changed', () => {
    botSpeedMs = getBotSpeedMs();
  });
  // Guards a staggered ghost-reveal callback from firing into a board
  // that has since been torn down (`stop()`) — a `setTimeout` outlives the
  // view switch that scheduled it.
  let stopped = false;
  //: So `mtg-game-ended` (which re-opens the app's side menu) fires once
  //: when the game finishes, not on every repaint of the finished board.
  let gameEndAnnounced = false;
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
  //
  // `owners` maps each expanded round back to the index of the requirement
  // it came from, so the picks can be regrouped into `target_groups` — one
  // list per *requirement*, in printed order — for the server (RULE 115.1,
  // `StackItem.target_groups`). A flat list alone can't say which slot a
  // declined "up to one" left empty, which is exactly what a spell like
  // Epic Confrontation ("target creature you control gets +1/+2 …. It
  // fights target creature you don't control.") needs to get right: pump
  // and fight must land on *different* creatures.
  //
  // ENG-30: a `count_max` requirement ("N or M target X", a genuine RULE
  // 601.2c range rather than "up to M") expands to `count_max` rounds
  // instead of `count` — but only the rounds past the printed minimum
  // (`count`) get the decline button (`castTargetModalHtml`'s `req.optional`
  // read), so a per-round *clone* with its own `optional` is pushed instead
  // of reusing one shared `req` reference the way every other requirement
  // here still does.
  function expandMultiTargetRequirements(requirements) {
    const expanded = [];
    const owners = [];
    let excludePicked = false;
    let excludeControllers = false;
    for (const [reqIndex, req] of requirements.entries()) {
      const minimum = req.count || 1;
      const total = req.count_max || minimum;
      if (total > 1) excludePicked = true;
      if (req.distinct_controllers) excludeControllers = true;
      for (let i = 0; i < total; i += 1) {
        expanded.push(
          req.count_max ? { ...req, optional: i >= minimum } : req
        );
        owners.push(reqIndex);
      }
    }
    return {
      requirements: expanded,
      owners,
      groupCount: requirements.length,
      excludePicked,
      excludeControllers,
    };
  }

  function isPlayableCardAction(a) {
    return a.type === 'cast_spell' || a.type === 'play_land' || a.type === 'activate_ability';
  }

  function dragActionsForInstance(instanceId) {
    if (!latestByInstance || !latestByInstance[instanceId]) return [];
    return latestByInstance[instanceId].filter(isPlayableCardAction);
  }

  function dragTargetsForActions(actions) {
    const ids = new Set();
    const playerIds = new Set();
    let battlefield = false;
    for (const action of actions) {
      if (action.type === 'play_land'
          || ((action.type === 'cast_spell' || action.type === 'activate_ability') && !action.requires_target)) {
        battlefield = true;
      }
      if (Array.isArray(action.targets)) {
        for (const req of action.targets) {
          if (!Array.isArray(req.options)) continue;
          for (const option of req.options) {
            if (option.instance_id != null) ids.add(String(option.instance_id));
            if (option.player_id != null) playerIds.add(String(option.player_id));
          }
        }
      }
    }
    return { battlefield, instanceIds: ids, playerIds };
  }

  function findDragTarget(element) {
    if (!element) return null;
    let el = element instanceof Element ? element : element.parentElement;
    while (el) {
      if (el.dataset && el.dataset.instanceId != null) {
        return { type: 'instance', instanceId: el.dataset.instanceId, element: el };
      }
      if (el.dataset && el.dataset.dropZone != null) {
        return { type: el.dataset.dropZone, element: el };
      }
      if (el.dataset && el.dataset.playerId != null) {
        return { type: 'player', playerId: el.dataset.playerId, element: el };
      }
      el = el.parentElement;
    }
    return null;
  }

  function isValidDragTarget(target) {
    if (!dragSource || !target) return false;
    const actions = dragActionsForInstance(dragSource.instanceId);
    if (!actions.length) return false;
    const targets = dragTargetsForActions(actions);
    if (target.type === 'battlefield') {
      if (!targets.battlefield) return false;
      // A played land/permanent always joins *this card's own controller's*
      // battlefield — never another player's board, however many are on
      // screen — so a drop only counts here if it landed on that same
      // player's own battlefield section (see the `dragstart` handler).
      if (!dragSource.playerId) return true;
      return target.element?.closest('[data-player-id]')?.dataset.playerId === dragSource.playerId;
    }
    if (target.type === 'instance') return targets.instanceIds.has(target.instanceId);
    if (target.type === 'player') return targets.playerIds.has(target.playerId);
    return false;
  }

  function clearDragHighlights() {
    root?.querySelectorAll('.gf-drag-target-valid, .gf-drag-source').forEach((el) => {
      el.classList.remove('gf-drag-target-valid', 'gf-drag-source');
    });
  }

  function highlightDragTargets() {
    clearDragHighlights();
    if (!dragSource) return;
    const actions = dragActionsForInstance(dragSource.instanceId);
    if (!actions.length) return;
    const targets = dragTargetsForActions(actions);
    const getByInstance = (id) => root?.querySelector(`[data-instance-id="${CSS.escape(id)}"]`);
    for (const id of targets.instanceIds) {
      const el = getByInstance(id);
      if (el) el.classList.add('gf-drag-target-valid');
    }
    for (const id of targets.playerIds) {
      const el = root?.querySelector(`[data-player-id="${CSS.escape(id)}"]`);
      if (el) el.classList.add('gf-drag-target-valid');
    }
    if (targets.battlefield) {
      // Scoped to the dragged card's *own* board — a shared/multiplayer view
      // renders one battlefield per player, and an unscoped querySelector
      // would always find whichever one happens to come first in
      // `boardOrder` (never this client's own, which is drawn last),
      // highlighting the wrong player's battlefield whenever they aren't it.
      const ownBoard = dragSource.playerId
        ? root?.querySelector(`[data-player-id="${CSS.escape(dragSource.playerId)}"]`)
        : root;
      const battlefield = ownBoard?.querySelector('[data-drop-zone="battlefield"]');
      if (battlefield) battlefield.classList.add('gf-drag-target-valid');
    }
    const sourceEl = root?.querySelector(`[data-instance-id="${CSS.escape(dragSource.instanceId)}"]`);
    if (sourceEl) sourceEl.classList.add('gf-drag-source');
  }

  function findTargetOptionForAction(action, instanceId, playerId) {
    if (!Array.isArray(action.targets)) return null;
    for (const req of action.targets) {
      if (!Array.isArray(req.options)) continue;
      for (const option of req.options) {
        if ((instanceId != null && String(option.instance_id) === instanceId) || (playerId != null && String(option.player_id) === playerId)) {
          return option;
        }
      }
    }
    return null;
  }

  function requirementOwnerIndexForOption(action, selectedOption) {
    if (!Array.isArray(action.targets)) return 0;
    const expanded = expandMultiTargetRequirements(action.targets || []);
    for (let i = 0; i < expanded.requirements.length; i += 1) {
      const req = expanded.requirements[i];
      if (!Array.isArray(req.options)) continue;
      for (const option of req.options) {
        if (String(option.instance_id) === String(selectedOption.instance_id) || String(option.player_id) === String(selectedOption.player_id)) {
          return expanded.owners[i];
        }
      }
    }
    return 0;
  }

  function prepareCastTargeting(action, selectedOption = null) {
    const requirements = action.targets || [];
    const expanded = expandMultiTargetRequirements(requirements);
    const send = {
      type: action.type,
      instance_id: action.instance_id,
      face: action.face,
      mode: action.mode,
      ability_index: action.ability_index,
    };
    if (action.type === 'cast_spell' && action.has_x) {
      send.x = readX(action.instance_id, action.face, action.blitz);
    }
    if (action.evoke) send.evoke = true;
    if (action.surge) send.surge = true;
    if (action.blitz != null) send.blitz = action.blitz;
    if (action.has_kicker) {
      send.kicker = readKicker(action.instance_id, action.face);
      if (action.kicker_has_x) send.kicker_x = readKickerX(action.instance_id, action.face);
    }
    if (action.pay_additional) send.pay_additional = true;
    if (action.bargained) send.bargained = true;
    if (action.gift_opponent_id) send.gift_opponent_id = action.gift_opponent_id;
    castTargeting = {
      instanceId: action.instance_id,
      requirements: expanded.requirements,
      reqIndex: 0,
      targets: [],
      groups: Array.from({ length: expanded.groupCount }, () => []),
      x: readX(action.instance_id, action.face, action.blitz),
      send,
      excludePicked: expanded.excludePicked,
      excludeControllers: expanded.excludeControllers,
    };
    if (selectedOption) {
      const owner = requirementOwnerIndexForOption(action, selectedOption);
      castTargeting.targets.push(selectedOption);
      if (expanded.groupCount > 1) {
        castTargeting.groups[owner].push(selectedOption);
      }
      castTargeting.reqIndex = 1;
    }
    finishCastIfReady();
  }

  function executeDroppedAction(target) {
    if (!dragSource || !target) return;
    const actions = dragActionsForInstance(dragSource.instanceId);
    if (!actions.length) return;

    if (target.type === 'battlefield') {
      const action = actions.find((a) => a.type === 'play_land'
        || ((a.type === 'cast_spell' || a.type === 'activate_ability') && !a.requires_target));
      if (!action) return;
      act({ type: action.type, instance_id: action.instance_id, face: action.face, mode: action.mode, ability_index: action.ability_index, x: readX(action.instance_id, action.face, action.blitz) });
      return;
    }

    const action = actions.find((a) => findTargetOptionForAction(a, target.instanceId, target.playerId));
    if (!action) return;
    const option = findTargetOptionForAction(action, target.instanceId, target.playerId);
    if (!option) return;

    if (action.targets && action.targets.length <= 1) {
      const send = {
        type: action.type,
        instance_id: action.instance_id,
        face: action.face,
        mode: action.mode,
        ability_index: action.ability_index,
      };
      if (action.type === 'cast_spell' && action.has_x) {
        send.x = readX(action.instance_id, action.face, action.blitz);
      }
      if (action.evoke) send.evoke = true;
      if (action.surge) send.surge = true;
      if (action.blitz != null) send.blitz = action.blitz;
      if (action.has_kicker) {
        send.kicker = readKicker(action.instance_id, action.face);
        if (action.kicker_has_x) send.kicker_x = readKickerX(action.instance_id, action.face);
      }
      if (action.pay_additional) send.pay_additional = true;
      if (action.bargained) send.bargained = true;
      if (action.gift_opponent_id) send.gift_opponent_id = action.gift_opponent_id;
      act({ ...send, targets: [option], x: send.x || 0 });
      return;
    }

    prepareCastTargeting(action, option);
  }

  function maybeReadDropTargetData(element) {
    if (!element) return null;
    const target = findDragTarget(element);
    return target && isValidDragTarget(target) ? target : null;
  }

  function setLatestByInstance(byInstance) {
    latestByInstance = byInstance;
  }

  // The user's current drag-and-drop arrangement of a pending `replacement_
  // order` choice's options (RULE 616.1) — an array of option ids, reset
  // whenever a fresh choice with a different option set appears. See
  // `replacementOrderHtml`/`confirmReplacementOrder`.
  let replacementOrderDraft = null;

  // Same idea for a pending `order_triggers` choice (RULE 603.3b), keyed by
  // `triggerOptionKey` rather than the raw option id — the id is just that
  // trigger's *current* position among the still-unordered set, which the
  // server re-derives (and re-numbers from 0) after every pick, so it can't
  // be used to recognize the "same" trigger again once the set has shrunk.
  // See `triggerOrderHtml`/`confirmTriggerOrder`.
  let triggerOrderDraft = null;

  // A stable identity for one `order_triggers` option, for matching the
  // same trigger across rounds despite its `id` being re-numbered each time
  // (see `triggerOrderDraft` above). Source name + ability text is what a
  // player actually distinguishes triggers by, so two genuinely
  // indistinguishable triggers (same source, same text) are — correctly —
  // not told apart here either.
  function triggerOptionKey(opt) {
    return `${opt.source_name || ''}␟${opt.label || opt.id}`;
  }

  function mount(el) {
    root = el;
  }

  let chatSending = false;
  let chatError = '';

  function chatPanelHtml() {
    const messages = (view.table_messages || []).map((message) => {
      const card = message.card_name || t('bd.chat.faceDownSpell');
      const text = message.kind === 'emote' ? message.text
        : t(`bd.chat.${message.action}`, { card }) + (message.ability_text ? ` ${message.ability_text}` : '');
      return `<li class="gf-chat-message ${message.kind === 'emote' ? 'is-chat' : 'is-announcement'}" data-message-id="${escapeAttr(message.id)}">
        <span class="gf-chat-author">${escapeHtml(message.author)}</span>
        <span>${escapeHtml(text)}</span>
      </li>`;
    }).join('');
    return `<section class="gf-chat" aria-label="${escapeAttr(t('bd.chat.heading'))}">
      <h4>${escapeHtml(t('bd.chat.heading'))}</h4>
      <ol class="gf-chat-messages" role="log" aria-live="polite" aria-relevant="additions" tabindex="0">
        ${messages || `<li class="hint">${escapeHtml(t('bd.chat.empty'))}</li>`}
      </ol>
      ${view.observer ? '' : `<div class="gf-chat-emotes">${TABLE_EMOTES.map((text, index) => `<button type="button" data-chat-emote="${escapeAttr(text)}" title="${escapeAttr(t(`bd.chat.emote${index}`))}" aria-label="${escapeAttr(t(`bd.chat.emote${index}`))}" ${chatSending ? 'disabled' : ''}>${escapeHtml(text)}</button>`).join('')}</div>`}
      ${chatError ? `<p class="gf-chat-error" role="alert">${escapeHtml(chatError)}</p>` : ''}
    </section>`;
  }

  async function sendChat(emote) {
    if (!sessionId || chatSending || !TABLE_EMOTES.includes(emote)) return;
    chatSending = true;
    chatError = '';
    render();
    try {
      const action = { type: 'emote', emote };
      const res = transport.sendAction ? await transport.sendAction(action)
        : await sendGameAction(sessionId, action);
      if (res.ok) {
        if (res.data) applyView(res.data);
      } else {
        chatError = t('bd.chat.failed');
      }
    } finally {
      chatSending = false;
      render();
    }
  }

  /** Begin driving `sessionId`, rendering `initialView` immediately. */
  function start(sid, initialView) {
    const isNewSession = sid !== sessionId;
    if (isNewSession) chatError = '';
    sessionId = sid;
    stopped = false;
    applyView(initialView);
    restoreUiDraft(initialView);
    // A game just became the thing on screen — let the app shell fold its
    // side menu away so the board gets the full width (app.js). Once per
    // session, not on every repaint.
    if (isNewSession) {
      resolvedGhosts = [];
      stopsSynced = false;
      document.dispatchEvent(new CustomEvent('mtg-game-started'));
      gameEndAnnounced = false;
    }
  }

  /** Feed in a view obtained some other way (rare — actions normally do this themselves). */
  function refresh(newView) {
    applyView(newView);
  }

  function setStatus(text, kind = '') {
    status = text;
    statusKind = kind;
    // Warnings go to the title bar (headerMessage.js): the inline status
    // line is covered by any open modal, e.g. a pending-choice dialog.
    setHeaderMessage(kind === 'warning' ? text : '');
  }

  // A stable-ish signature for one stack item, for spotting which entries
  // disappeared between two views (i.e. resolved / were countered) so they
  // can linger a moment as greyed-out ghosts in the rail.
  function stackItemSig(item) {
    const obj = item.object || item.source || {};
    return `${obj.instance_id ?? ''}|${item.description || ''}|${item.kind || ''}|${obj.name || ''}`;
  }

  function pushResolvedGhost(item) {
    const key = `${Date.now()}-${Math.random()}`;
    // Keep the raw stack item so the ghost renders as the same mini card
    // view as the live entries (`stackItemHtml` with `{ ghost: true }`).
    resolvedGhosts = [
      ...resolvedGhosts.slice(-(GHOST_MAX_ITEMS - 1)),
      { key, item },
    ];
    setTimeout(() => {
      resolvedGhosts = resolvedGhosts.filter((g) => g.key !== key);
      if (!stopped) render();
    }, GHOST_LIFETIME_MS);
  }

  /** A ghost item's card name (spell card, or ability source). */
  function ghostItemName(item) {
    return (item.object || item.source || {}).name || '';
  }

  // A bot opponent's cast/activation is drained off the stack by the server
  // before the client ever sees a view with it on the stack (`run_bots` in
  // multiplayer, `_advance_solo_bots` in solo, both answer to completion
  // before returning) — so the stack-diff above never fires a ghost for it.
  // Build a minimal synthetic stack item from the `move_log` label instead
  // so it still flashes up in the rail as a resolved ghost. `null` for
  // labels that don't put anything on the stack (play_land, pass_priority…).
  function syntheticStackItemFromMoveLabel(label) {
    const sep = label.indexOf(': ');
    const kind = sep === -1 ? label : label.slice(0, sep);
    const name = sep === -1 ? '' : label.slice(sep + 2);
    if (!name) return null;
    if (kind === 'cast_spell') {
      return { kind: 'spell', object: { name }, type_line: '' };
    }
    if (kind === 'activate_ability') {
      return { kind: 'ability', category: 'activated_ability', source: { name }, description: name };
    }
    return null;
  }

  function applyView(data) {
    const prevStack = view?.state?.stack || [];
    const samePriorSessionForStack = sessionId === lastDraftSessionId;
    view = data;
    if (root) root.dataset.bugReportSession = sessionId || "";
    // Ghost-trail: entries that were on the stack last view and aren't now
    // (resolved or countered) linger briefly so it stays visible what just
    // happened — in the solo modes too, where the engine auto-drains it.
    // Skipped across a session switch (a fresh `start()` shares nothing).
    if (samePriorSessionForStack && prevStack.length) {
      const now = new Set((data?.state?.stack || []).map(stackItemSig));
      for (const item of prevStack) {
        if (!now.has(stackItemSig(item))) pushResolvedGhost(item);
      }
    }
    // PLR-6: only a *real* move — this session's `move_log` actually grew
    // (or shrank, e.g. a take-back) since the last view we invalidated
    // against, or we've switched sessions entirely — invalidates a
    // half-assembled block/targeting selection. A view that merely arrived
    // (a reconnect resending the same committed position — see
    // multiplayer_ws.py's `subscribe_game` broadcast) must not wipe it, or
    // any other player's socket blipping would nuke everyone's in-progress
    // picks.
    const newLen = data?.move_log?.length ?? null;
    const prevLen = lastDraftMoveLogLen;
    const samePriorSession = sessionId === lastDraftSessionId;
    const changed = !samePriorSession || lastDraftMoveLogLen === null || newLen !== lastDraftMoveLogLen;
    lastDraftSessionId = sessionId;
    lastDraftMoveLogLen = newLen;
    if (changed) {
      castTargeting = null;
      blockDraft = new Map();
    }
    // VIS-7: flash a bot's newest casts/activations up in the rail stack as
    // ghosts, on the same "move_log actually grew" signal above (never on a
    // reconnect rebroadcast of the unchanged position, and never across a
    // session switch). A bot's whole turn arrives as one pushed view
    // (`run_bots` runs it to completion before the single broadcast), so the
    // ghosts are staggered by `botSpeedMs` rather than all revealed at once.
    if (
      data?.perspective &&
      samePriorSession &&
      prevLen !== null &&
      newLen !== null &&
      newLen > prevLen &&
      Array.isArray(data.move_actors)
    ) {
      const labels = data.move_log.slice(prevLen, newLen);
      const actors = data.move_actors.slice(prevLen, newLen);
      const liveStackNames = new Set(
        (data?.state?.stack || []).map((it) => (it.object || it.source || {}).name || ''),
      );
      let revealIndex = 0;
      labels.forEach((label, i) => {
        const actorId = actors[i];
        if (!actorId || actorId === data.perspective) return;
        // A ghost only for a cast/activation that never showed on this
        // client's own stack (a mid-stack view means the stack-diff ghosts
        // it for real when it resolves) and isn't already ghosting.
        const ghostItem = syntheticStackItemFromMoveLabel(label);
        if (
          !ghostItem ||
          liveStackNames.has(ghostItemName(ghostItem)) ||
          resolvedGhosts.some((g) => ghostItemName(g.item) === ghostItemName(ghostItem))
        ) {
          return;
        }
        const delay = revealIndex * botSpeedMs;
        revealIndex += 1;
        const fire = () => {
          if (stopped) return;
          pushResolvedGhost(ghostItem);
          render();
        };
        if (delay <= 0) fire();
        else setTimeout(fire, delay);
      });
    }
    if (data?.state?.game_over && !gameEndAnnounced) {
      gameEndAnnounced = true;
      // The game is over — bring the app's side menu back (app.js).
      document.dispatchEvent(new CustomEvent('mtg-game-ended'));
    }
    onViewChange(data);
    render();
  }

  // --- PLR-6: in-progress UI selection persistence ------------------------
  // Mirrors `blockDraft`/`castTargeting` server-side as they're built (see
  // `set_ui_draft`/`GameSession._ui_drafts`) so a genuine reconnect — a new
  // tab, not just a socket blip — can rebuild the modal instead of losing
  // it outright, since neither was ever otherwise sent to the server.
  // Fire-and-forget: these are UI conveniences, not game actions, so a
  // failed save just means a worse reconnect experience, not a broken game.

  function persistBlockDraft() {
    if (!sessionId) return;
    const assignments = Array.from(blockDraft, ([blocker, attacker]) => ({ blocker, attacker }));
    saveUiDraft(sessionId, view?.perspective ?? null, assignments.length ? { kind: 'block', assignments } : null);
  }

  function persistCastTargetingDraft() {
    if (!sessionId) return;
    saveUiDraft(sessionId, view?.perspective ?? null, castTargeting ? { kind: 'cast', castTargeting } : null);
  }

  // Best-effort rehydration on `start()`: only accepts the saved draft if
  // it still lines up with what the fresh view actually offers — an
  // attacker/blocker pairing whose creatures are gone, or a cast whose
  // target requirements changed shape, is silently dropped rather than
  // risking a confusing half-restored modal (the eventual submit, if any,
  // is still validated server-side regardless).
  function restoreUiDraft(v) {
    const draft = v?.ui_draft;
    if (!draft) return;
    if (draft.kind === 'block' && Array.isArray(draft.assignments)) {
      const offers = new Map(
        (v.legal_actions || [])
          .filter((a) => a.type === 'declare_blockers')
          .map((a) => [a.instance_id, new Set((a.legal_attackers || []).map((x) => x.instance_id))]),
      );
      const restored = new Map();
      for (const entry of draft.assignments) {
        const attackers = offers.get(entry?.blocker);
        if (attackers && attackers.has(entry?.attacker)) restored.set(entry.blocker, entry.attacker);
      }
      if (restored.size) blockDraft = restored;
    } else if (draft.kind === 'cast' && draft.castTargeting?.send) {
      const ct = draft.castTargeting;
      const action = findTargetableAction(
        ct.instanceId, ct.send.type, ct.send.ability_index, ct.send.face, ct.send.mode,
        ct.send.pay_additional, ct.send.bargained, ct.send.evoke, ct.send.gift_opponent_id, ct.send.surge, ct.send.blitz,
      );
      if (action) {
        const expanded = expandMultiTargetRequirements(action.targets || []);
        const sameShape = ct.isTapChoice || ct.isSacrificeChoice || ct.isDiscardChoice
          ? Array.isArray(ct.requirements)
          : expanded.requirements.length === (ct.requirements || []).length;
        if (sameShape && Number.isInteger(ct.reqIndex)) castTargeting = ct;
      }
    }
  }

  async function withBusy(fn) {
    busy = true;
    try {
      render();
      await fn();
    } finally {
      busy = false;
      render();
    }
  }

  async function act(action) {
    if (!sessionId) return;
    await withBusy(async () => {
      const res = transport.sendAction
        ? await transport.sendAction(action)
        : await sendGameAction(sessionId, action);
      if (res.ok) {
        // A caller with its own transport may repaint from a pushed view
        // instead (multiplayer does — every seat is updated over the
        // socket), in which case it returns no `data` and we leave the
        // board alone rather than painting a stale reply over it.
        if (res.data) applyView(res.data);
        setStatus('', '');
      } else {
        // A failed action never changes `priorityWindowKey()`, so if this
        // was the auto-skip's own `pass_priority` attempt, `skipAttemptedForKey`
        // would otherwise stay set to a window that never actually got
        // passed — wedging the ⏭/auto-skip logic for the rest of the game
        // (nothing else ever resets it). Clearing it here lets the next
        // render retry instead of silently going inert.
        skipAttemptedForKey = null;
        if (res.status === 400) {
          setStatus(t('bd.msg.actionNotAllowed', { detail: res.data?.detail ?? '' }), 'warning');
        } else if (res.status === 404) {
          setStatus('Spielsitzung abgelaufen.', 'warning');
        } else {
          setStatus(`Fehler (${res.status}).`, 'warning');
        }
      }
    });
  }

  async function rewind() {
    if (!sessionId) return;
    await withBusy(async () => {
      const res = transport.rewind
        ? await transport.rewind(1)
        : await rewindGame(sessionId, 1);
      if (res.ok) {
        applyView(res.data);
        setStatus(t('bd.msg.lastTurnUndone'), 'ok');
      } else {
        setStatus(t('bd.msg.undoFailed', { status: res.status }), 'warning');
      }
    });
  }

  // --- Rendering ------------------------------------------------------------

  function render() {
    if (!root || !view) return;
    const previousChat = root.querySelector('.gf-chat-messages');
    const chatAtBottom = !previousChat || previousChat.scrollHeight - previousChat.scrollTop - previousChat.clientHeight <= CHAT_BOTTOM_THRESHOLD_PX;
    const chatScrollTop = previousChat?.scrollTop || 0;
    const s = view.state;
    // Keep the countdown length (a server setting) current before anything
    // reads it — `railTimerHtml`/`autoPassArmed` both do, and `render()`
    // runs before `syncAutoPass()`.
    autoPassSeconds = serverTimerSeconds();
    const dummy = s.players.find((p) => p.is_dummy) || null;
    // The seat this client is playing (multiplayer; null in every solo mode
    // and for an observer). Their board is drawn *last* — i.e. nearest the
    // player, like sitting at a table — with the opponents above it.
    const seatId = view.perspective || null;
    const live = boardOrder(s.players, seatId);
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
    setLatestByInstance(byInstance);
    const stackNonEmpty = s.stack.length > 0;
    if (!pending) choiceAside = false;
    updateTargetOverlays(s);
    updateAbilitySourceOverlays(s, pending);

    root.innerHTML = `
      <div class="goldfish${compactView ? ' compact-view' : ''}${(pending && !choiceAside) || castTargeting ? ' choosing' : ''}" style="--gf-scale: ${(getBoardScale() / 100).toFixed(2)}">
        <aside class="gf-rail">
          <div class="gf-rail-turn">
            <span class="gf-turn" title="${escapeAttr(t('bd.turn.rule500', { n: s.internal_turn.number }))}">${escapeHtml(t('bd.turn.label', { n: s.turn_nr }))}</span>
            <span class="gf-step">${escapeHtml(labelPhase(s.current_phase))} · ${escapeHtml(labelStep(s.current_step))}</span>
            ${s.day_night ? `<span class="gf-daynight gf-daynight-${s.day_night}">${s.day_night === 'night' ? '🌙 Nacht' : '☀️ Tag'}</span>` : ''}
          </div>

          ${railTimerHtml()}
          ${railStopsHtml()}

          ${railStackHtml(s)}

          ${chatPanelHtml()}

          ${controlsHtml(stackNonEmpty, pending, gameOver)}
        </aside>

        <div class="gf-stage">
          ${turnControlBannerHtml(s)}

          ${dummy ? opponentStripHtml(dummy) : ''}

          ${planechaseHtml(s, actions)}

          ${gameOver ? gameOverHtml(s, seatId ? s.players.find((p) => p.id === seatId) : live[0]) : ''}
          ${statusHtml()}
          ${view.observer ? `<p class="server-status gf-observer-note">${escapeHtml(t('bd.observerNote'))}</p>` : ''}
          ${waitingOnChoiceHtml(s)}
          ${pending ? pendingChoiceHtml(pending, choiceAside) : ''}
          ${castTargeting ? castTargetModalHtml() : ''}

          ${blockerPanelHtml(actions, s)}

          ${boardsHtml(live, s, byInstance, pending, seatId)}

          ${delayedTriggersPanelHtml(view)}
        </div>
      </div>
    `;
    wire();
    const chatList = root.querySelector('.gf-chat-messages');
    if (chatList) chatList.scrollTop = chatAtBottom ? chatList.scrollHeight : chatScrollTop;
    syncAutoPass();
    // A repaint mid-countdown rebuilds the bar at its inline default; catch
    // it up to the live remaining value straight away so it doesn't flash
    // back to full for up to a second.
    if (autoPassTimer !== null) paintCountdown();
  }

  // RULE 901: the Planechase strip — the face-up plane (901.7) with its own
  // text, how many planes are left behind it, and the planar-die roll (a
  // special action, RULE 901.6, offered by the server only on its roller's
  // own turn and only when the {X} is payable). Renders nothing at all in a
  // game with no planar deck, which is every non-Planechase game.
  function planechaseHtml(s, actions) {
    const plane = s.active_plane;
    if (!plane) return '';
    const roll = (actions || []).find((a) => a.type === 'roll_planar_die');
    const rollButton = roll
      ? `<button type="button" class="primary" data-action='${escapeAttr(JSON.stringify({ type: 'roll_planar_die' }))}' title="${escapeAttr(t('bd.planar.rollTitle'))}">${escapeHtml(t('bd.planar.rollButton', { cost: roll.cost_label || '{0}' }))}</button>`
      : '';
    return `
      <div class="gf-planechase">
        <div class="gf-planechase-plane">
          <span class="gf-planechase-label" title="Aktive Ebene (Regel 901.7)">🌌 Ebene</span>
          <!-- Deliberately no data-hover-card: a plane is not in the card
               cache at all (the bulk importer drops the "planar" layout), so
               a hover lookup by name could only ever miss. Note: no
               backticks in here — this comment sits inside a template
               literal, where one would end the string mid-comment. -->
          <strong title="${escapeAttr(plane.type_line || '')}">${escapeHtml(plane.name)}</strong>
          <span class="gf-planechase-count" title="${escapeAttr(t('bd.planar.remaining'))}">${escapeHtml(t('bd.planar.inStack', { count: s.planar_deck_count || 0 }))}</span>
        </div>
        ${rollButton}
      </div>`;
  }

  // --- Board layout: turn order, stacked column vs. 2x2 pod grid ------------

  /**
   * The boards in the order they're drawn — **turn order**, rotated so this
   * client's own seat comes last.
   *
   * `GameState.players` *is* the turn order: `next_active_index` walks that
   * list cyclically (RULE 500.1), skipping dummies and players who have
   * left (RULE 104.3a). Rotating rather than sorting keeps that cycle
   * intact while preserving the older rule that your own board is drawn
   * last, i.e. nearest you. Reading the layout row-major then goes around
   * the table the way the turns actually do: the first board is whoever
   * plays after you, the last one is you.
   *
   * No seat (solo modes, and an observer) means nothing to rotate to, so
   * the plain turn order stands.
   */
  function boardOrder(players, seatId) {
    const live = players.filter((p) => !p.is_dummy);
    const mine = live.findIndex((p) => p.id === seatId);
    if (mine < 0) return live;
    return live.slice(mine + 1).concat(live.slice(0, mine + 1));
  }

  // (The turn-order strip that used to sit in the topbar is gone: who is
  // active and who holds priority is shown on each player's own banner now,
  // and the topbar itself has been replaced by the left rail.)

  // --- Board layout: stacked column vs. 2x2 pod grid ------------------------

  /**
   * Whether the boards tile 2x2 instead of stacking.
   *
   * From three live boards up (`services/lobby.py` opens up to four seats).
   * Two boards stack better than they tile — full width is worth more than
   * having them side by side — but three or four stacked means the player
   * below the fold is off-screen entirely. Deliberately derived from the
   * live view rather than persisted: it's a consequence of how many people
   * are at the table, not a preference. Observers get it too (they watch
   * the same pod), which is why this doesn't key off `view.perspective`.
   *
   * Also off on a screen too narrow for two columns — see `podGridMedia`.
   */
  function podGrid() {
    if (podGridMedia && !podGridMedia.matches) return false;
    return (view?.state?.players || []).filter((p) => !p.is_dummy).length >= 3;
  }

  //: Which column of the 2x2 each board lands in. The grid places seats
  //: **clockwise** — top-left, top-right, bottom-right, bottom-left — so
  //: turn order runs around the table and the last seat is back beside the
  //: first. That is deliberately *not* `index % 2`: the third board is on
  //: the right, not the left. Mirrors main.css's `.gf-pod-grid` placement
  //: rules; change one and you must change the other.
  const POD_COLUMNS = ['left', 'right', 'right', 'left'];

  /**
   * Which side one board's zone column sits on, as a `gf-zones-*` suffix.
   *
   * Stacked: the plain left/right toggle, same for every board. Pod grid:
   * mirrored per column so "innen"/"außen" means the same thing on both
   * sides of the grid — see `zonesInside`.
   *
   * @param {number} index Position in the rendered board list.
   * @param {number} total How many boards are drawn — an odd count means
   *   the last one spans the whole bottom row, so it follows the left
   *   column's rule (it starts at the left edge) rather than its nominal
   *   clockwise slot.
   */
  function zonesSideFor(index, total) {
    if (!podGrid()) return zonesLeft ? 'left' : 'right';
    const spansTheRow = total % 2 === 1 && index === total - 1;
    const leftColumn = spansTheRow || POD_COLUMNS[index] === 'left';
    return zonesInside === leftColumn ? 'right' : 'left';
  }

  // One control, three toolbars (observer / priority / plain), so it's a
  // helper rather than three copies. In the pod grid the label reads out the
  // current state ("Zonen: innen") because there are only two of them and
  // which one you're in isn't otherwise obvious at a glance; the tooltip
  // says what the click does. Stacked, the side is plain to see, so the
  // label stays the action it always was.
  function zonesSideButtonHtml() {
    return podGrid()
      ? `<button id="gf-zones-side" type="button" title="${escapeAttr(t('bd.zonesSide.podTitle', { where: zonesInside ? t('bd.zonesSide.podOutside') : t('bd.zonesSide.podInside') }))}">${escapeHtml(t('bd.zonesSide.podLabel', { state: zonesInside ? t('bd.zonesSide.podInner') : t('bd.zonesSide.podOuter') }))}</button>`
      : `<button id="gf-zones-side" type="button" title="${escapeAttr(t('bd.zonesSide.plainTitle'))}">${t('bd.zonesSide.plainLabel')}</button>`;
  }

  function controlsHtml(stackNonEmpty, pending, gameOver) {
    const extra = extraControlsFn(busy)
      .map(
        (c) =>
          `<button type="button" data-extra="${escapeAttr(c.id)}" title="${escapeAttr(c.title || '')}" ${busy || c.disabled ? 'disabled' : ''}>${c.label}</button>`,
      )
      .join('');
    // An observer has no seat and therefore no actions at all (the server
    // sends them an empty `legal_actions`) — only the layout toggle and
    // whatever the caller added (e.g. "Zuschauen beenden") stay useful.
    if (view.observer) {
      return `
        <div class="gf-controls gf-rail-controls">
          ${zonesSideButtonHtml()}
          ${extra}
        </div>`;
    }
    // With interactive priority (RULE 117, shared games) the turn isn't
    // advanced by anyone deciding it should be — it moves when players
    // pass, so "Nächster Schritt" is replaced by "Passen" and the whole
    // toolbar keys off who holds priority rather than whose turn it is.
    if (interactivePriority()) return priorityControlsHtml(pending, gameOver, extra);

    // Whether *this* client may drive the turn. In a shared game only the
    // active player can (RULE 500.1, enforced server-side too); solo modes
    // have no perspective and always can.
    const myTurn = !view.perspective || view.state.active_player_id === actingSeat();
    return `
      <div class="gf-controls gf-rail-controls">
        <button id="gf-advance" type="button" class="primary" ${busy || gameOver || pending || !myTurn ? 'disabled' : ''}>${t('bd.ctrl.advance')}</button>
        ${allowFastForward ? `<button id="gf-next-decision" type="button" title="${escapeAttr(t('bd.ctrl.nextDecisionTitle2'))}" ${busy || gameOver || pending || !myTurn ? 'disabled' : ''}>${t('bd.ctrl.nextDecision')}</button>` : ''}
        ${stackNonEmpty && !pending ? `<button type="button" data-action='${escapeAttr(JSON.stringify({ type: 'pass_priority' }))}'>${t('bd.ctrl.passResolveStack')}</button>` : ''}
        ${allowRewind ? `<button id="gf-rewind" type="button" ${busy || !view.can_rewind ? 'disabled' : ''}>${t('bd.ctrl.rewind')}</button>` : ''}
        ${zonesSideButtonHtml()}
        ${extra}
      </div>`;
  }

  /** Whether this session plays priority out for real (RULE 117). */
  function interactivePriority() {
    return !!view?.priority?.interactive && !view.observer;
  }

  /**
   * The seat this client currently acts as (MEC-51 / RULE 720): its own,
   * or another player's whose turn/combat it controls. The server sets
   * `view.acting_as` (= `perspective` when not controlling anyone).
   */
  function actingSeat() {
    return view?.acting_as || view?.perspective || null;
  }

  /** Whether this client is the one the game is currently waiting on. */
  function hasPriority() {
    if (!view?.priority) return false;
    const pid = view.priority.player_id;
    return (
      (!!actingSeat() && pid === actingSeat()) ||
      (!!view.perspective && pid === view.perspective)
    );
  }

  // The shared-game toolbar. "Passen" is the only way forward: a step ends
  // when every player passes in succession on an empty stack (RULE 117.4),
  // so there is deliberately no "advance the turn" button to press.
  function priorityControlsHtml(pending, gameOver, extra) {
    // "Passen" / "Nächste Aktion" are deliberately *not* here — they live on
    // this client's own board banner (`playerBoardHtml`'s `priorityBits`),
    // next to the cards you're actually looking at. The rail keeps only the
    // layout/table controls.
    return `
      <div class="gf-controls gf-rail-controls gf-priority-controls">
        ${zonesSideButtonHtml()}
        ${extra}
      </div>`;
  }

  // "Passen" lives only on the priority holder's own board banner
  // (`playerBoardHtml`) now — right next to the cards, not off in the rail.
  // Still a data attribute rather than an id so `wire()` can bind however
  // many the page ends up with.
  function passButtonHtml(disabled, extraClass = '') {
    // With an empty stack, say where passing leads ("To combat →") rather
    // than a bare "Pass"; with something on it, passing resolves it.
    const next = view.priority?.next_step;
    const toNext = next ? t(`bd.ctrl.passTo.${next}`) : '';
    const label = view.state.stack.length > 0
      ? t('bd.ctrl.passResolve')
      : (toNext && toNext !== `bd.ctrl.passTo.${next}` ? toNext : t('bd.ctrl.pass'));
    return `<button type="button" class="primary${extraClass}" data-pass-priority title="${escapeAttr(t('bd.ctrl.passTitle'))}" ${disabled ? 'disabled' : ''}>${label}</button>`;
  }

  // Empty priority windows are already skipped automatically and
  // unconditionally (`skipEmptyArmed`/`syncAutoPass`), so there is no manual
  // button for *that*. These are the deliberate speed-ups (VIS-12), offered
  // next to "Passen": "Pass this turn" (opponents' turns only) and "Skip to
  // end step" (your own turn only) arm a server-side yield; while one is
  // armed it is replaced by a single cancel button, which — unlike the pass button — works
  // without priority, because a yielding seat is passed for and so rarely
  // holds it. (Goldfisch's `#gf-next-decision` is unrelated — a server-side
  // fast-forward over whole *steps*, solo only.)
  function yieldButtonsHtml(disabled, extraClass = '') {
    const armed = myYield();
    if (armed) {
      const label = armed === 'end_step' ? t('bd.ctrl.yieldEndStepActive') : t('bd.ctrl.yieldTurnActive');
      return `<button type="button" class="gf-yield gf-yield-active${extraClass}" data-yield="clear" title="${escapeAttr(t('bd.ctrl.yieldCancelTitle'))}" ${disabled ? 'disabled' : ''}>${label}</button>`;
    }
    const s = view.state;
    if (!view.perspective) return '';
    if (s.active_player_id !== actingSeat()) {
      return `<button type="button" class="gf-yield${extraClass}" data-yield="turn" title="${escapeAttr(t('bd.ctrl.passTurnTitle'))}" ${disabled ? 'disabled' : ''}>${t('bd.ctrl.passTurn')}</button>`;
    }
    if (s.current_step === 'end') return '';
    return `<button type="button" class="gf-yield${extraClass}" data-yield="end_step" title="${escapeAttr(t('bd.ctrl.skipToEndTitle'))}" ${disabled ? 'disabled' : ''}>${t('bd.ctrl.skipToEnd')}</button>`;
  }

  // VIS-12: a seat that has armed a yield is visibly passing its turn.
  function yieldBadgeHtml(playerId) {
    const mode = view.priority?.yields?.[playerId];
    if (!mode) return '';
    const label = mode === 'end_step' ? t('bd.badge.yieldEndStep') : t('bd.badge.yieldTurn');
    return `<span class="gf-yield-badge">${escapeHtml(label)}</span>`;
  }

  // The priority indicator on a player's banner (`playerBoardHtml`): a bare
  // ⚡, shown only on whichever banner currently holds priority — never a
  // standing "waiting for X" state on anyone else's. The live countdown that
  // used to sit here has moved to the rail's progress bar (`railTimerHtml`).
  function priorityBadgeHtml(holdsPriority, isMe, playerName_) {
    if (!holdsPriority) return '';
    const title = isMe ? t('bd.priority.mine') : t('bd.priority.holder', { name: playerName_ });
    return `<span class="gf-priority-badge${isMe ? ' gf-priority-mine' : ''}" title="${escapeAttr(title)}">⚡</span>`;
  }

  function waitingOnChoiceHtml(s) {
    const waiting = s.waiting_on_choice;
    if (!waiting) return '';
    const who = playerName(waiting.decider_id || waiting.player_id);
    const what = waiting.prompt ? ` (${escapeHtml(waiting.prompt)})` : '';
    return `<p class="server-status pending gf-waiting-choice">⏳ ${escapeHtml(who)} trifft gerade eine Entscheidung${what} …</p>`;
  }

  // MEC-51 / RULE 720: "Du kontrollierst den Zug von X" (Mindslaver, Sorin
  // Markov, Emrakul, Worst Fears) / "…die Kampfphase von X" (Secret of
  // Bloodbending). Shows on the controller's board while a window is active
  // — and the mirror notice on the controlled player's own board.
  function turnControlBannerHtml(s) {
    const me = view.perspective;
    // MEC-51b: an in-progress Word of Command — a short "you play a card
    // from X's hand" window, distinct from the turn/combat control below.
    const woc = s.word_of_command;
    if (woc && woc.controller_id === me) {
      return `<p class="server-status gf-turn-control gf-turn-control-driving">${escapeHtml(t('bd.turnControl.wocDriving', { name: playerName(woc.target_id) }))}</p>`;
    }
    if (woc && woc.target_id === me) {
      return `<p class="server-status pending gf-turn-control gf-turn-control-locked">${escapeHtml(t('bd.turnControl.wocLocked', { name: playerName(woc.controller_id) }))}</p>`;
    }
    const controls = (s.turn_controls || []).filter((c) => c.phase === 'active');
    if (!controls.length) return '';
    // I'm driving someone else's turn/combat.
    const mine = controls.find((c) => c.controller_id === me && c.controlled_id !== me);
    if (mine) {
      const scopeWord = mine.scope === 'combat' ? t('bd.turnControl.scopeCombat') : t('bd.turnControl.scopeTurn');
      return `<p class="server-status gf-turn-control gf-turn-control-driving">${escapeHtml(t('bd.turnControl.driving', { scope: scopeWord, name: playerName(mine.controlled_id), source: mine.source_name ? ` (${mine.source_name})` : '' }))}</p>`;
    }
    // My own turn/combat is being controlled by someone else.
    const over = controls.find((c) => c.controlled_id === me && c.controller_id !== me);
    if (over) {
      const scopeWord = over.scope === 'combat' ? t('bd.turnControl.scopeYourCombat') : t('bd.turnControl.scopeYourTurn');
      return `<p class="server-status pending gf-turn-control gf-turn-control-locked">${escapeHtml(t('bd.turnControl.locked', { name: playerName(over.controller_id), scope: scopeWord }))}</p>`;
    }
    return '';
  }

  // RULE 509.1a: the defending player assigns blockers. Each offer from
  // `legal_actions` is one creature that could block, with the attackers it
  // may legally be assigned to; the whole block is submitted at once (see
  // `blockDraft`). Only ever non-empty for a player who isn't the attacker.
  function blockerPanelHtml(actions, s) {
    const offers = actions.filter((a) => a.type === 'declare_blockers');
    if (!offers.length) return '';
    const rows = offers
      .map((offer) => {
        const chosen = blockDraft.get(offer.instance_id);
        const options = [
          `<option value="">${t('bd.block.noBlock')}</option>`,
          ...offer.legal_attackers.map(
            (a) =>
              `<option value="${a.instance_id}"${chosen === a.instance_id ? ' selected' : ''}>${escapeHtml(a.name)}</option>`,
          ),
        ].join('');
        return `
          <div class="gf-block-row">
            <span class="gf-block-blocker" data-hover-card="${escapeAttr(offer.name)}">${escapeHtml(offer.name)}</span>
            <span class="gf-block-arrow">blockt</span>
            <select class="gf-block-pick" data-block-blocker="${offer.instance_id}">${options}</select>
          </div>`;
      })
      .join('');
    const count = blockDraft.size;
    return `
      <section class="gf-block-panel">
        <h4>${t('bd.block.declareHeading')}</h4>
        <p class="hint">${escapeHtml(t('bd.block.hint', { name: playerName(s.active_player_id) }))}</p>
        ${rows}
        <div class="gf-controls">
          <button id="gf-submit-blocks" type="button" class="primary" ${busy ? 'disabled' : ''}>
            ${count ? escapeHtml(t('bd.block.confirm', { count })) : t('bd.block.confirmNone')}
          </button>
          <button id="gf-clear-blocks" type="button" ${busy || !count ? 'disabled' : ''}>${t('bd.block.reset')}</button>
        </div>
      </section>`;
  }

  async function submitBlocks() {
    // An empty assignment list is a legal, complete answer (RULE 509.1a —
    // "declare no blocks" is a real turn-based action, not the absence of
    // one), so this must not be guarded on `blockDraft.size`.
    const assignments = Array.from(blockDraft, ([blocker, attacker]) => ({ blocker, attacker }));
    await act({ type: 'declare_blockers', assignments });
  }

  // Every board, in order. Stacked they're just concatenated, as they always
  // were; in the pod grid they need a wrapper to tile in, and each board
  // needs to know its own position so its zone column can mirror (see
  // `zonesSideFor`). DOM order is unchanged either way — opponents first,
  // this client's own seat last — so "row-major" and "drawn last is nearest
  // you" stay the same statement.
  function boardsHtml(live, s, byInstance, pending, seatId) {
    const boards = live
      .map((p, i) => playerBoardHtml(p, s, byInstance, pending, seatId, i, live.length))
      .join('');
    return podGrid() ? `<div class="gf-pod-grid">${boards}</div>` : boards;
  }

  // One player's full board: mana/life header, command/library/graveyard/
  // exile column, battlefield (row-grouped by type) + hand.
  function playerBoardHtml(p, s, byInstance, pending, seatId = null, index = 0, total = 1) {
    const bf = s.battlefield.filter((o) => o.controller_id === p.id);
    const isMe = seatId != null && p.id === seatId;
    // "Is this hand mine to look at?" — true for my own seat, and for both
    // boards in a solo/Replay session (no perspective means no opponent:
    // the puzzle editor is meant to see everything). An observer has no
    // seat *and* no hand, so every hand there is somebody else's.
    const ownHand = isMe || (seatId == null && !view.observer);
    const isActive = s.active_player_id === p.id;
    const seat = seatStatus(p.id);
    const badges = [
      isActive ? `<span class="gf-seat-badge gf-seat-active">${t('bd.seat.active')}</span>` : '',
      p.has_lost
        ? `<span class="gf-seat-badge gf-seat-out">${p.loss_reason === 'conceded' ? t('bd.seat.conceded') : t('bd.seat.out')}</span>`
        : '',
      // Not a rules state at all — this player's browser is gone. The
      // server passes priority for them meanwhile, so the game keeps
      // moving; the badge is why it looks like they're doing nothing.
      seat?.connected === false
        ? `<span class="gf-seat-badge gf-seat-away" title="${escapeAttr(t('bd.seat.awayTitle'))}">${t('bd.seat.away')}</span>`
        : '',
    ].join('');
    // The banner colour this seat picked in the Multiplayer setup — the
    // whole title bar, so at a pod of four you find your own board (and
    // your opponents') by colour rather than by reading four names.
    const bannerCss = bannerStyle(seat?.banner_color);
    const bannerAttrs = bannerCss
      ? ` style="${escapeAttr(bannerCss)}" title="${escapeAttr(`Banner-Farbe: ${bannerColorLabel(seat.banner_color)}`)}"`
      : '';
    // RULE 117: whose window it is, and the buttons that end it, right on
    // the banner of the board you're actually looking at — the toolbar at
    // the top of the page is off-screen once two boards are drawn. They sit
    // directly beside the name, which puts life and counters across from it
    // on the right — the same left-name/right-life shape every other seat's
    // banner has, instead of the buttons taking that right-hand slot on
    // your own.
    const holdsPriority = interactivePriority() && view.priority?.player_id === p.id;
    const priorityDisabled = busy || !!pending || !hasPriority();
    // "Zurücknehmen (n)" only for this client's own banner, only when the
    // table configured a take-back budget and this seat has some left, and
    // only when the transport actually offers a take-back (multiplayer).
    const takebacksLeft = isMe ? view.takebacks_remaining?.[view.perspective] : undefined;
    const takebackBtn = isMe && transport.takeBack && takebacksLeft > 0
      ? `<button type="button" class="gf-banner-takeback" data-banner-takeback ${busy ? 'disabled' : ''}>${escapeHtml(t('bd.banner.takeback', { count: takebacksLeft }))}</button>`
      : '';
    const priorityBits = s.game_over
      ? takebackBtn
      : !interactivePriority()
        ? takebackBtn
        : isMe
          ? `${priorityBadgeHtml(holdsPriority, true, p.name)}${passButtonHtml(priorityDisabled, ' gf-banner-pass')}${yieldButtonsHtml(busy || !!pending, ' gf-banner-yield')}${takebackBtn}`
          : `${priorityBadgeHtml(holdsPriority, false, p.name)}${yieldBadgeHtml(p.id)}`;
    // Folding an opponent away is only offered at a pod-sized table — with
    // one opponent there is nothing to scroll past.
    const opponents = s.players.filter((o) => !o.is_dummy && o.id !== seatId).length;
    const foldable = seatId != null && !isMe && opponents > 1;
    const folded = foldable && collapsedBoards.has(p.id);
    return `
      <section class="gf-player-board${isMe ? ' gf-own-board' : ''}${seatId && !isMe ? ' gf-opponent-board' : ''}${p.has_lost ? ' gf-board-out' : ''}${folded ? ' gf-board-folded' : ''}" data-player-id="${escapeAttr(p.id)}">
        <header class="gf-player-board-head${bannerCss ? ' gf-banner-tinted' : ''}"${bannerAttrs}>
          ${
            foldable
              ? `<button type="button" class="gf-board-fold" data-fold-board="${escapeAttr(p.id)}" title="${folded ? escapeAttr(t('bd.fold.expand')) : escapeAttr(t('bd.fold.collapse'))}" aria-expanded="${folded ? 'false' : 'true'}">${folded ? '▸' : '▾'}</button>`
              : ''
          }
          <h3>${escapeHtml(p.name)}${badges}</h3>
          ${priorityBits ? `<div class="gf-banner-priority">${priorityBits}</div>` : ''}
          <div class="gf-banner-stats">
            ${manaPoolHtml(p.mana_pool)}
            ${manaPotentialHtml(view.mana_potential?.[p.id])}
            ${lifeBox(t('bd.zone.life'), p.life)}
            ${playerCountersHtml(p, s)}
          </div>
        </header>
        ${folded ? foldedBoardHtml(p, bf) : ''}
        <div class="gf-play gf-zones-${zonesSideFor(index, total)}"${folded ? ' hidden' : ''}>
          <aside class="gf-side">
            <div class="gf-zone gf-command">
              <h4>${t('bd.zone.commandZone')}</h4>
              ${objGrid(p.command, '–', byInstance, pending)}
            </div>
            <div class="gf-zone gf-library">
              <h4>${t('bd.zone.library')}</h4>
              <p class="library-count">${escapeHtml(t('bd.zone.libraryCount', { count: p.library_count }))}</p>
              ${libraryTopHtml(p, byInstance, pending)}
            </div>
            ${collapsibleZoneHtml('gf-graveyard', t('bd.zone.graveyard'), `${p.id}:graveyard`, p.graveyard.length, zoneListHtml(p.graveyard, t('bd.zone.empty')))}
            ${collapsibleZoneHtml('gf-exile', t('bd.zone.exile'), `${p.id}:exile`, p.exile.length, objGrid(p.exile, t('bd.zone.empty'), byInstance, pending))}
          </aside>

          <div class="gf-main">
            <div class="gf-zone gf-battlefield" data-drop-zone="battlefield">
              <div class="gf-bf-head">
                <h4>Battlefield (${bf.length})</h4>
                <label class="gf-bf-toggle" title="${escapeAttr(t('bd.bf.landsOwnRowTitle'))}">
                  <input type="checkbox" class="gf-rows-toggle" ${threeRows ? 'checked' : ''} />
                  ${t('bd.bf.landsOwnRow')}
                </label>
                <label class="gf-bf-toggle" title="${escapeAttr(t('bd.bf.staticsTitle'))}">
                  <input type="checkbox" class="gf-statics-toggle" ${showStatics ? 'checked' : ''} />
                  ${t('bd.bf.statics')}
                </label>
              </div>
              ${battlefieldHtml(bf, byInstance, pending)}
            </div>

            ${showStatics ? staticEffectsPanelHtml(view, s) : ''}

            ${handAreaHtml(p, s, byInstance, pending, ownHand)}
          </div>
        </div>
      </section>`;
  }

  // What a folded-away opponent still shows: how much of everything they
  // have. Enough to know whether they're worth unfolding, and all of it is
  // public information the board prints anyway (a hidden zone is only ever
  // a count here, same as when the board is open — RULE 400.2).
  function foldedBoardHtml(p, bf) {
    const creatures = bf.filter((o) => o.is_creature).length;
    const counts = [
      tPlural('bd.fold.permanents', bf.length),
      tPlural('bd.fold.creatures', creatures),
      t('bd.fold.hand', { count: p.hand_count != null ? p.hand_count : p.hand.length }),
      t('bd.fold.library', { count: p.library_count }),
      t('bd.fold.graveyard', { count: p.graveyard.length }),
      t('bd.fold.exile', { count: p.exile.length }),
    ];
    return `<p class="gf-board-fold-summary">${counts.map(escapeHtml).join(' · ')}</p>`;
  }

  // A hand the server redacted (RULE 400.2 — an opponent's hand never
  // leaves the server, `services/game_session.py`) arrives as an empty
  // `hand` plus a non-zero `hand_count`; draw that many card backs so the
  // board still shows *how much* they're holding. A genuinely empty hand
  // has `hand_count === 0` and falls through to the normal "leer".
  function handHtml(p, byInstance, pending, isOwn = true) {
    const count = p.hand_count != null ? p.hand_count : p.hand.length;
    if (!p.hand.length && count > 0) {
      // Nothing here is information — the cards themselves never left the
      // server — so an opponent's row of backs is off unless asked for.
      if (!isOwn && !getShowOpponentHand()) {
        return `<p class="empty-state gf-hand-hidden">${escapeHtml(tPlural('bd.hand.hiddenCount', count))}</p>`;
      }
      return `<div class="card-grid">${Array.from(
        { length: count },
        () => `<div class="gf-card-slot">${faceDownCardHtml()}</div>`,
      ).join('')}</div>`;
    }
    // Cards actually *in* the array for someone else's hand are ones the
    // server chose to send, i.e. revealed — always shown, whatever the
    // toggle says.
    return objGrid(p.hand, 'leer', byInstance, pending);
  }

  // Only rendered on a hand that isn't yours (see `ownHand`) — in
  // Replay/Puzzle mode both boards are yours to edit, so there is nothing
  // to hide and no toggle.
  function opponentHandToggleHtml() {
    return `
      <label class="gf-bf-toggle gf-hand-toggle" title="${escapeAttr(t('bd.hand.showOppTitle'))}">
        <input type="checkbox" class="gf-opp-hand-toggle" ${getShowOpponentHand() ? 'checked' : ''} />
        ${t('bd.hand.showOppShort')}
      </label>`;
  }

  // One face-down card: the player's own chosen sleeve if they uploaded one
  // (Einstellungen tab, `setAssets`), otherwise a plain patterned back.
  function faceDownCardHtml() {
    if (assetsSleeveImageUrl) {
      return `<div class="card has-image gf-face-down"><img src="${escapeAttr(assetsSleeveImageUrl)}" alt="${escapeAttr(t('bd.hand.faceDownAlt'))}" /></div>`;
    }
    return `<div class="card gf-face-down" title="${escapeAttr(t('bd.hand.faceDownAlt'))}"></div>`;
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
      <p class="library-top-hint">${t('bd.libraryTop.visible')}</p>
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
  // except `replacement_order` (RULE 616.1) and `order_triggers`
  // (RULE 603.3b), which get a drag-and-drop reorderable list instead (see
  // `replacementOrderHtml`/`triggerOrderHtml`), and `scry`/`surveil`, which
  // get inline card-face thumbnails instead of bare name buttons (see
  // `lookTopChoiceHtml`). `aside` is a push-aside escape hatch
  // (`data-choice-aside` below) — a player deciding e.g. a surveil may want
  // to check the board (a graveyard, a permanent's text) before answering
  // rather than being fully blocked.
  function pendingChoiceHtml(pending, aside = false) {
    const icon = CHOICE_ICONS[pending.kind] || '❔';
    const heading = pending.prompt || pending.description || t('bd.choice.needed');
    const body = pending.kind === 'replacement_order'
      ? replacementOrderHtml(pending)
      : pending.kind === 'order_triggers'
        ? triggerOrderHtml(pending)
        : pending.kind === 'scry' || pending.kind === 'surveil' || pending.kind === 'reorder_top' || pending.kind === 'look_hand'
          ? lookTopChoiceHtml(pending)
          : pending.kind === 'clash'
            ? clashChoiceHtml(pending)
          // MEC-46: a "vote for one of these objects" ballot (Council's
          // Judgment / Custodi Squire) — options carry a `card_id`, so the
          // same face-thumbnail renderer scry/surveil use reads far better
          // than bare name buttons.
          : pending.kind === 'vote_object'
            ? lookTopChoiceHtml(pending)
            : simpleChoiceButtonsHtml(pending);
    const asideLabel = aside ? t('bd.choice.asideShow') : t('bd.choice.asidePush');

    return `
      <div class="gf-modal-overlay${aside ? ' aside' : ''}">
        <div class="gf-modal" role="dialog" aria-modal="true">
          <div class="gf-modal-head">
            <span class="gf-modal-icon">${icon}</span>
            <div>
              <h4>${escapeHtml(heading)}</h4>
              <p class="gf-modal-who">${escapeHtml(t('bd.choice.forWhom', { name: playerName(pending.player_id) }))}</p>
              ${pending.source_name ? `<p class="gf-modal-source">${escapeHtml(t('bd.choice.triggeredBy', { name: pending.source_name }))}</p>` : ''}
            </div>
            <button type="button" class="gf-modal-aside" data-choice-aside title="${escapeAttr(t('bd.choice.asideTitle'))}">${asideLabel}</button>
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
        if (opt.action?.type === 'cast_spell') return `<span>${escapeHtml(opt.action.name || '')}</span>${castTargetHtml(opt.action)}`;
        if (opt.id === 'decline') {
          const action = JSON.stringify({ type: 'decline' });
          return `<button type="button" class="gf-decline" data-action='${escapeAttr(action)}'>${escapeHtml(opt.label || t('bd.choice.chooseNothing'))}</button>`;
        }
        const action = JSON.stringify(opt.action || { type: 'choose', option_id: opt.id, instance_id: opt.instance_id, name: opt.label });
        const hover = opt.instance_id != null ? ` data-hover-card="${escapeHtml(opt.label || '')}"` : '';
        return `<button type="button"${hover} data-action='${escapeAttr(action)}'>${escapeHtml(opt.label || opt.id)}</button>`;
      })
      .join('');

    return `<div class="gf-choice-options">${buttons}</div>`;
  }

  // scry/surveil (RULE 701.18/701.31): the away and order phases both offer
  // exactly the looked-at cards plus a decline, but unlike a generic search
  // the player needs to actually *read* each card to decide — a bare name
  // button forces a hover to see it, so this renders an inline face thumbnail
  // per option (`opt.card_id`, see `_look_top_choice`) alongside the label,
  // still hoverable for the full-size tooltip via `data-hover-card`.
  function lookTopChoiceHtml(pending) {
    const options = pending.options || [];
    const cards = options
      .map((opt) => {
        if (opt.id === 'decline') {
          const action = JSON.stringify({ type: 'decline' });
          return `<button type="button" class="gf-lt-card gf-lt-decline" data-action='${escapeAttr(action)}'>
            <span class="gf-lt-decline-label">${escapeHtml(opt.label || 'Fertig')}</span>
          </button>`;
        }
        const action = JSON.stringify({ type: 'choose', option_id: opt.id, instance_id: opt.instance_id, name: opt.label });
        const img = opt.card_id ? cardImageUrl(opt.card_id, 'small', 'front') : null;
        return `<button type="button" class="gf-lt-card" data-hover-card="${escapeHtml(opt.label || '')}" data-action='${escapeAttr(action)}'>
          ${img ? `<img class="gf-lt-card-img" src="${escapeAttr(img)}" alt="${escapeAttr(opt.label || '')}" loading="lazy">` : ''}
          <span class="gf-lt-card-label">${escapeHtml(opt.label || opt.id)}</span>
        </button>`;
      })
      .join('');
    return `<div class="gf-lt-options">${cards}</div>`;
  }

  // RULE 701.30c: both clash cards are public while their owners decide,
  // even though they are still physically in hidden libraries.  The server
  // sends them separately as `state.clash_revealed`; show both faces here,
  // then offer only this pending choice's owner the top/bottom decision.
  function clashChoiceHtml(pending) {
    const revealed = view.state?.clash_revealed || [];
    const faces = revealed.map((card) => {
      const img = card.card_id ? cardImageUrl(card.card_id, 'small', 'front') : null;
      return `<article class="gf-clash-card" data-hover-card="${escapeHtml(card.name || '')}">
        ${img ? `<img class="gf-lt-card-img" src="${escapeAttr(img)}" alt="${escapeAttr(card.name || '')}" loading="lazy">` : ''}
        <span class="gf-lt-card-label">${escapeHtml(card.name || 'Karte')}</span>
      </article>`;
    }).join('');
    const buttons = (pending.options || []).map((opt) => {
      const action = JSON.stringify({ type: 'choose', option_id: opt.id, name: opt.label });
      return `<button type="button" class="${opt.id === 'bottom' ? 'gf-decline' : 'primary'}" data-action='${escapeAttr(action)}'>${escapeHtml(opt.label || opt.id)}</button>`;
    }).join('');
    return `<div class="gf-clash-reveal">${faces}</div><div class="gf-choice-options">${buttons}</div>`;
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
      <p class="gf-reorder-hint">${t('bd.reorder.hintEffects')}</p>
      <ul class="gf-reorder-list">${items}</ul>
      <div class="gf-modal-foot">
        <button type="button" class="primary" data-reorder-confirm>${t('bd.common.confirm')}</button>
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
        const action = {
          type: 'choose', option_id: opt.id, instance_id: opt.instance_id, name: opt.label,
        };
        const res = transport.sendAction
          ? await transport.sendAction(action)
          : await sendGameAction(sessionId, action);
        if (!res.ok) {
          setStatus(t('bd.msg.actionNotAllowed', { detail: res.data?.detail ?? res.status }), 'warning');
          break;
        }
        if (res.data) applyView(res.data);
        remaining = remaining.slice(1);
      }
    });
    replacementOrderDraft = null;
  }

  // RULE 603.3b: 2+ of the active player's triggers fired simultaneously
  // (`state.interactive_ordering` opt-in). Same drag-and-drop convenience as
  // `replacementOrderHtml` above: the player arranges the *whole* set once,
  // confirming replays it as a sequence of single picks
  // (`confirmTriggerOrder`). Each item shows the source permanent's name
  // and the ability's own oracle text (`label` — see `_trigger_order_
  // choice`'s docstring) rather than just a bare description, so ordering
  // two similarly-named triggers doesn't come down to guessing which is
  // which (ENG-4's frontend half).
  function triggerOrderHtml(pending) {
    const options = pending.options || [];
    const keys = options.map(triggerOptionKey);
    // (Re)seed the draft whenever the offered option set doesn't match what
    // was last dragged (a fresh choice, or the previous one was just
    // answered and the remaining triggers re-offered).
    if (!triggerOrderDraft
        || triggerOrderDraft.length !== keys.length
        || !keys.every((k) => triggerOrderDraft.includes(k))) {
      triggerOrderDraft = keys.slice();
    }
    const byKey = Object.fromEntries(options.map((o) => [triggerOptionKey(o), o]));
    const items = triggerOrderDraft
      .map((key, i) => {
        const opt = byKey[key];
        if (!opt) return '';
        const source = opt.source_name
          ? `<span class="gf-reorder-source">${escapeHtml(opt.source_name)}</span>`
          : '';
        return `<li class="gf-reorder-item" draggable="true" data-key="${escapeAttr(key)}">
          <span class="gf-reorder-handle" aria-hidden="true">⠿</span>
          <span class="gf-reorder-index">${i + 1}.</span>
          <span class="gf-reorder-text">${source}<span class="gf-reorder-label">${escapeHtml(opt.label || opt.id)}</span></span>
        </li>`;
      })
      .join('');
    return `
      <p class="gf-reorder-hint">${t('bd.reorder.hintTriggers')}</p>
      <ul class="gf-reorder-list gf-trigger-order-list">${items}</ul>
      <div class="gf-modal-foot">
        <button type="button" class="primary" data-trigger-order-confirm>${t('bd.common.confirm')}</button>
      </div>
    `;
  }

  // Replays the player's dragged order as a sequence of single `choose`
  // picks, mirroring `confirmReplacementOrder` — but matched by
  // `triggerOptionKey` rather than raw option id, since `resolve_trigger_
  // order_choice` re-numbers the remaining triggers' ids from 0 every
  // round (the id is a position in the shrinking `_ordering_active` list,
  // not a stable identifier). Stops automating (leaving whatever the server
  // returned on screen) the moment a step's key is no longer offered or a
  // different pending choice shows up instead — which is exactly what
  // happens, by design, when the placed trigger itself needs a target/mode/
  // "you may" choice (ENG-4): the ordering choice simply isn't re-offered
  // until that's answered.
  async function confirmTriggerOrder(order) {
    if (!sessionId || !order || !order.length) return;
    await withBusy(async () => {
      let remaining = order.slice();
      while (remaining.length) {
        const pending = view.state?.pending_choice;
        if (!pending || pending.kind !== 'order_triggers') break;
        const opt = (pending.options || []).find((o) => triggerOptionKey(o) === remaining[0]);
        if (!opt) break;
        const action = { type: 'choose', option_id: opt.id, name: opt.label };
        const res = transport.sendAction
          ? await transport.sendAction(action)
          : await sendGameAction(sessionId, action);
        if (!res.ok) {
          setStatus(t('bd.msg.actionNotAllowed', { detail: res.data?.detail ?? res.status }), 'warning');
          break;
        }
        if (res.data) applyView(res.data);
        remaining = remaining.slice(1);
      }
    });
    triggerOrderDraft = null;
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
    root.querySelectorAll('[data-chat-emote]').forEach((button) => {
      button.addEventListener('click', () => sendChat(button.dataset.chatEmote));
    });
    root.querySelector('#gf-advance')?.addEventListener('click', () => act({ type: 'advance_step' }));
    root.querySelector('#gf-next-decision')?.addEventListener('click', () => act({ type: 'advance_to_decision' }));
    root.querySelector('#gf-rewind')?.addEventListener('click', rewind);
    // Every pass button on the page (toolbar + each own-board banner).
    root.querySelectorAll('[data-pass-priority]').forEach((el) => {
      el.addEventListener('click', () => act({ type: 'pass_priority' }));
    });
    // VIS-12: arm/cancel a server-side yield (`set_yield`).
    root.querySelectorAll('[data-yield]').forEach((el) => {
      el.addEventListener('click', () => act({ type: 'set_yield', mode: el.dataset.yield }));
    });
    wireStopsPanel();
    // Interrupt the rail countdown for this window (same effect as touching
    // the board — the player is clearly still deciding).
    root.querySelector('[data-timer-interrupt]')?.addEventListener('click', () => {
      cancelAutoPassForThisWindow();
      render();
    });
    // The take-back button lives on the player's own banner now (only when
    // the table configured a budget and this client has some left).
    root.querySelector('[data-banner-takeback]')?.addEventListener('click', () => {
      if (transport.takeBack) transport.takeBack();
    });
    // Fold an opponent's board away at a table of 3+ (see `collapsedBoards`).
    root.querySelectorAll('[data-fold-board]').forEach((el) => {
      el.addEventListener('click', () => {
        const id = el.dataset.foldBoard;
        if (collapsedBoards.has(id)) collapsedBoards.delete(id);
        else collapsedBoards.add(id);
        render();
      });
    });
    // Expand / collapse a Friedhof or Exil zone body (see `expandedZones`).
    root.querySelectorAll('[data-zone-toggle]').forEach((el) => {
      el.addEventListener('click', () => {
        const key = el.dataset.zoneToggle;
        if (expandedZones.has(key)) expandedZones.delete(key);
        else expandedZones.add(key);
        render();
      });
    });
    // Show/hide an opponent's face-down hand (their cards are never on the
    // wire either way — RULE 400.2).
    root.querySelectorAll('.gf-opp-hand-toggle').forEach((el) => {
      el.addEventListener('change', (e) => {
        saveSettings({ showOpponentHand: e.target.checked });
        render();
      });
    });

    // Touching the board at all means "I'm still thinking" — the countdown
    // for this window stops rather than passing out from under the player.
    if (interactivePriority()) {
      root.querySelector('.goldfish')?.addEventListener('pointerdown', (e) => {
        // Only the stage counts as "thinking" — the rail is where you pass /
        // interrupt / adjust on purpose, so a click in there must not also
        // silently cancel the countdown.
        if (e.target.closest('.gf-rail')) return;
        cancelAutoPassForThisWindow();
      });
    }

    // RULE 509.1a block assembly: each pick only updates the local draft
    // (and re-renders so the confirm button's count follows); nothing is
    // sent until "Block bestätigen".
    root.querySelectorAll('[data-block-blocker]').forEach((el) => {
      el.addEventListener('change', () => {
        const blocker = Number(el.dataset.blockBlocker);
        const attacker = Number(el.value);
        if (attacker) blockDraft.set(blocker, attacker);
        else blockDraft.delete(blocker);
        persistBlockDraft();
        render();
      });
    });
    root.querySelector('#gf-submit-blocks')?.addEventListener('click', submitBlocks);
    root.querySelector('#gf-clear-blocks')?.addEventListener('click', () => {
      blockDraft = new Map();
      persistBlockDraft();
      render();
    });

    root.querySelectorAll('[data-extra]').forEach((el) => {
      const control = extraControlsFn(busy).find((c) => c.id === el.dataset.extra);
      if (control) el.addEventListener('click', control.onClick);
    });

    root.querySelectorAll('[data-action]').forEach((el) => {
      el.addEventListener('click', () => {
        const action = JSON.parse(el.dataset.action);
        // RULE 508.1g makes paying an attack tax optional. The board asks at
        // the declaration click, before the backend's auto-payment path can
        // consume floating mana; declining simply leaves this creature out
        // of combat.
        if (action.attack_tax_amount > 0) {
          if (!window.confirm(t('bd.attackTax.confirm', { cost: `{${action.attack_tax_amount}}` }))) return;
          delete action.attack_tax_amount;
          action.pay_attack_tax = true;
        }
        act(action);
      });
    });

    if (!dragHandlersInstalled) {
      dragHandlersInstalled = true;
      root.addEventListener('dragover', (e) => {
        e.preventDefault();
        if (e.dataTransfer) e.dataTransfer.dropEffect = 'move';
        const target = maybeReadDropTargetData(e.target);
        if (!target) return;
      });
      root.addEventListener('drop', (e) => {
        const target = maybeReadDropTargetData(e.target);
        e.preventDefault();
        if (target) {
          executeDroppedAction(target);
        }
        dragSource = null;
        clearDragHighlights();
      });
    }

    root.querySelectorAll('[data-draggable-card="true"]').forEach((el) => {
      el.addEventListener('dragstart', (e) => {
        const slot = el.closest('[data-instance-id]');
        const instanceId = slot?.dataset.instanceId;
        if (!instanceId) return;
        // Which player's own board this card lives on — a shared/multiplayer
        // board renders one `[data-drop-zone="battlefield"]` *per player*, so
        // "the battlefield" is ambiguous without this: an unscoped
        // `querySelector` always finds whichever board happens to come first
        // in `boardOrder` (every board but this client's own, which is drawn
        // last/nearest), highlighting — and, worse, accepting a drop onto —
        // some other player's battlefield whenever they aren't that first one.
        dragSource = { instanceId, playerId: slot.closest('[data-player-id]')?.dataset.playerId || null };
        e.dataTransfer.effectAllowed = 'move';
        e.dataTransfer.setData('text/plain', '');
        highlightDragTargets();
      });
      el.addEventListener('dragend', () => {
        dragSource = null;
        clearDragHighlights();
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
      // RULE 603.3b trigger-order popup shares the same `.gf-reorder-list`
      // drag mechanics above; only the confirm step differs — items carry
      // `data-key` (a stable `triggerOptionKey`, not a round-numbered id).
      root.querySelector('[data-trigger-order-confirm]')?.addEventListener('click', () => {
        const order = Array.from(reorderList.querySelectorAll('.gf-reorder-item')).map((li) => li.dataset.key);
        confirmTriggerOrder(order);
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

    // Flip the static-zone column (library/graveyard/…) to the other side —
    // or, in the pod grid, between the middle and the outer edges. Two
    // separate persisted settings because the layouts they describe are
    // different (see `zonesInside`), one button because it's one question.
    root.querySelector('#gf-zones-side')?.addEventListener('click', () => {
      if (podGrid()) {
        zonesInside = !zonesInside;
        setCookie('gf_zones_pod', zonesInside ? 'inside' : 'outside', 365);
      } else {
        zonesLeft = !zonesLeft;
        setCookie('gf_zones_side', zonesLeft ? 'left' : 'right', 365);
      }
      render();
    });

    // Push a pending-choice popup aside (or bring it back).
    root.querySelector('[data-choice-aside]')?.addEventListener('click', () => {
      choiceAside = !choiceAside;
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

    // "🔄 peek other face" — a DFC's client-only preview toggle, not a real
    // transform (see `flippedForView`/`showsBackFace`).
    root.querySelectorAll('[data-flip-toggle]').forEach((el) => {
      el.addEventListener('click', (event) => {
        event.stopPropagation(); // don't also trigger the card's own hover/click behaviour
        const iid = Number(el.dataset.flipToggle);
        if (flippedForView.has(iid)) flippedForView.delete(iid);
        else flippedForView.add(iid);
        render();
      });
    });

    // {X} spells read the announced value from the adjacent number input at
    // click time rather than baking it into a static data-action attribute.
    root.querySelectorAll('[data-cast-x]').forEach((el) => {
      el.addEventListener('click', () => {
        const { iid, face, mode, entwine, evoke, surge, blitz, pay_additional, bargained, gift_opponent_id } = JSON.parse(el.dataset.castX);
        const x = readX(iid, face, blitz);
        const kicked = readKicker(iid, face);
        const kicker_x = readKickerX(iid, face);
        act({ type: 'cast_spell', instance_id: iid, x, face, kicked, kicker_x, mode, entwine, evoke, surge, blitz, pay_additional, bargained, gift_opponent_id });
      });
    });

    root.querySelectorAll('[data-tap-x]').forEach((el) => {
      el.addEventListener('click', () => {
        const { iid, ability_index, option_index } = JSON.parse(el.dataset.tapX);
        submitManaActivation({ type: 'tap_for_mana', instance_id: iid, ability_index, option_index, x: readX(iid, null) });
      });
    });

    root.querySelectorAll('[data-activate-x]').forEach((el) => {
      el.addEventListener('click', () => {
        const { iid, ability_index } = JSON.parse(el.dataset.activateX);
        const x = readX(iid, null);
        act({ type: 'activate_ability', instance_id: iid, ability_index, x });
      });
    });

    root.querySelectorAll('[data-cast-target-start]').forEach((el) => {
      el.addEventListener('click', () => {
        const info = JSON.parse(el.dataset.castTargetStart);
        const iid = Number(info.iid);
        const action = findTargetableAction(
          iid, info.type, info.ability_index, info.face, info.mode,
          info.pay_additional, info.bargained, info.evoke, info.gift_opponent_id, info.surge, info.blitz,
        );
        if (!action) return;
        const x = action.has_x ? readX(iid, info.face, info.blitz) : 0;
        const kicked = action.has_kicker ? readKicker(iid, info.face) : 0;
        const kicker_x = action.kicker_has_x ? readKickerX(iid, info.face) : 0;
        const send = info.type === 'activate_ability'
          ? { type: 'activate_ability', instance_id: iid, ability_index: info.ability_index, name: action.name }
          : {
            type: 'cast_spell', instance_id: iid, name: action.name, face: info.face, kicked, kicker_x,
            mode: info.mode, entwine: info.entwine, evoke: action.evoke, surge: action.surge, blitz: action.blitz, pay_additional: action.pay_additional,
            bargained: action.bargained, gift_opponent_id: action.gift_opponent_id,
          };
        const {
          requirements, owners, groupCount, excludePicked, excludeControllers,
        } = expandMultiTargetRequirements(action.targets || []);
        castTargeting = {
          instanceId: iid, requirements, owners, reqIndex: 0, targets: [], x, send,
          groups: Array.from({ length: groupCount }, () => []),
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
          // …and into this round's own requirement group, so a declined
          // "up to one" leaves an *empty* group rather than shifting every
          // later pick one slot up (see `expandMultiTargetRequirements`).
          const owner = castTargeting.owners?.[castTargeting.reqIndex];
          if (owner != null) castTargeting.groups?.[owner]?.push(target);
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
        persistCastTargetingDraft();
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
        const info = JSON.parse(container.dataset.splitAction);
        const x = container.dataset.splitTotal === 'x' ? readX(info.instance_id, null) : null;
        const total = x ?? Number(container.dataset.splitTotal);
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
        const send = { ...info, color_split: split, ...(x !== null ? { x } : {}) };
        if (info.type === 'tap_for_mana') submitManaActivation(send);
        else act(send);
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

    root.querySelectorAll('[data-sacrifice-choice-start]').forEach((el) => {
      el.addEventListener('click', () => {
        const info = JSON.parse(el.dataset.sacrificeChoiceStart);
        const iid = Number(info.iid);
        const action = (view?.legal_actions || []).find(
          (a) => a.type === info.type && a.instance_id === iid && a.ability_index === info.ability_index,
        );
        if (!action || !action.sacrifice_cost) return;
        const { options } = action.sacrifice_cost;
        // "Sacrifice a <type>" cost (RULE 602.1) — which permanent pays it
        // is the player's own choice, not an engine auto-pick; same
        // one-pick modal as `tap_cost` above, just always exactly one pick
        // and dispatched as `sacrifice_choice` instead of `tap_choices`.
        const requirements = [{ label: t('bd.sacrifice.permanent'), options, optional: false }];
        const send = info.type === 'activate_ability'
          ? { type: 'activate_ability', instance_id: iid, ability_index: info.ability_index }
          : { type: 'tap_for_mana', instance_id: iid, ability_index: info.ability_index, option_index: info.option_index };
        castTargeting = {
          instanceId: iid, requirements, reqIndex: 0, targets: [], x: 0, send,
          excludePicked: true, isSacrificeChoice: true,
        };
        finishCastIfReady();
      });
    });

    root.querySelectorAll('[data-discard-choice-start]').forEach((el) => {
      el.addEventListener('click', () => {
        const info = JSON.parse(el.dataset.discardChoiceStart);
        const iid = Number(info.iid);
        const action = findTargetableAction(
          iid, 'cast_spell', undefined, info.face, info.mode,
          info.pay_additional, info.bargained, info.evoke, info.gift_opponent_id, info.surge, info.blitz,
        );
        if (!action || !action.discard_cost) return;
        const { count, options } = action.discard_cost;
        // "As an additional cost to cast this spell, discard N cards" (RULE
        // 601.2b) — which cards pay it is the player's own choice (RULE
        // 602.1), not an engine auto-pick. Same one-pick-at-a-time modal as
        // `tap_cost`/`sacrifice_cost` above; `excludePicked` stops the same
        // card being picked twice, `isDiscardChoice` routes the picks to
        // `discard_choices` in `finishCastIfReady`.
        const requirements = Array.from({ length: count }, () => ({
          label: t('bd.discard.card'), options, optional: false,
        }));
        const send = {
          type: 'cast_spell', instance_id: iid, name: action.name,
          face: info.face, mode: info.mode, evoke: action.evoke, surge: action.surge, blitz: action.blitz,
          pay_additional: action.pay_additional,
          bargained: action.bargained, gift_opponent_id: action.gift_opponent_id,
        };
        castTargeting = {
          instanceId: iid, requirements, reqIndex: 0, targets: [], x: 0, send,
          excludePicked: true, isDiscardChoice: true,
        };
        finishCastIfReady();
      });
    });
  }

  // Modal-DFC (RULE 712.10) actions for the same card differ only by
  // `face` — key any face-scoped DOM lookup on `instance_id:face` so a
  // card offering both faces at once (e.g. both `has_x`) doesn't collide
  // on a bare instance_id. Blitz instances also get separate X inputs.
  function xKey(instanceId, face, blitz) {
    const key = face ? `${instanceId}:${face}` : String(instanceId);
    return blitz != null ? `${key}:blitz:${blitz}` : key;
  }

  function submitManaActivation(send) {
    const action = (view?.legal_actions || []).find(
      (a) => a.type === send.type && a.instance_id === send.instance_id && a.ability_index === send.ability_index,
    );
    if (!action?.tap_cost) { act(send); return; }
    const count = action.tap_cost.count === 'x' ? send.x : action.tap_cost.count;
    castTargeting = {
      instanceId: send.instance_id,
      requirements: Array.from({ length: count }, () => ({
        label: 'zu tappende bleibende Karte', options: action.tap_cost.options, optional: false,
      })),
      reqIndex: 0, targets: [], x: send.x || 0, send,
      excludePicked: true, isTapChoice: true,
    };
    finishCastIfReady();
  }

  function readX(instanceId, face, blitz) {
    const input = root.querySelector(`[data-x-input="${xKey(instanceId, face, blitz)}"]`);
    return Math.max(0, Math.floor(Number(input?.value) || 0));
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

  // Kicker's own {X} (RULE 702.33b, PAR-7 — Emblazoned Golem-shaped): a
  // second, independent value from the spell's own X, keyed/read the same way.
  function readKickerX(instanceId, face) {
    const input = root.querySelector(`[data-kicker-x-input="${kickerKey(instanceId, face)}"]`);
    return Math.max(0, Math.floor(Number(input?.value) || 0));
  }

  // ``mode`` disambiguates a modal spell's several `cast_spell` offers
  // (RULE 700.2 — same instance_id/type/face, one per mode or mode
  // combination via `_modal_cast_actions`) — without it this always
  // returned whichever mode `legal_actions` happened to list first,
  // regardless of which of the offered buttons was actually clicked.
  // Compared via JSON (not `===`) since a "choose N" mode is an array of
  // indices; absent on both sides (a non-modal spell/activated ability)
  // normalizes to the same `null` key either way.
  function findTargetableAction(iid, type, abilityIndex, face, mode, payAdditional, bargained, evoke, giftOpponentId, surge, blitz) {
    const modeKey = JSON.stringify(mode ?? null);
    return (view?.legal_actions || []).find(
      (a) =>
        a.type === type &&
        a.instance_id === iid &&
        (type !== 'activate_ability' || a.ability_index === abilityIndex) &&
        (a.face || undefined) === (face || undefined) &&
        JSON.stringify(a.mode ?? null) === modeKey &&
        Boolean(a.pay_additional) === Boolean(payAdditional) &&
        Boolean(a.bargained) === Boolean(bargained) &&
        Boolean(a.evoke) === Boolean(evoke) &&
        Boolean(a.surge) === Boolean(surge) &&
        (a.blitz ?? null) === (blitz ?? null) &&
        // RULE 702.174a: the per-opponent "cast + promise a gift" offers are distinct entries.
        (a.gift_opponent_id || null) === (giftOpponentId || null),
    );
  }

  function finishCastIfReady() {
    if (!castTargeting) return;
    if (castTargeting.reqIndex >= castTargeting.requirements.length) {
      const { send, targets, groups, x, isTapChoice, isSacrificeChoice, isDiscardChoice } = castTargeting;
      castTargeting = null;
      if (isTapChoice) {
        // A "tap N untapped <type>s you control" cost choice (RULE 602.1),
        // not a RULE 115 target — send the picked instance ids as
        // `tap_choices` instead of `targets`.
        act({ ...send, tap_choices: targets.map((t) => t.instance_id) });
      } else if (isSacrificeChoice) {
        // A "Sacrifice a <type>" cost choice (RULE 602.1) — always exactly
        // one pick, sent as `sacrifice_choice` instead of `targets`.
        act({ ...send, sacrifice_choice: targets[0].instance_id });
      } else if (isDiscardChoice) {
        // A "discard N cards" additional cast cost choice (RULE 601.2b /
        // 602.1) — the picked hand cards, sent as `discard_choices` instead
        // of `targets`.
        act({ ...send, discard_choices: targets.map((t) => t.instance_id) });
      } else if ((groups || []).length > 1) {
        // 2+ requirements: send the per-requirement partition too (RULE
        // 115.1), so each targeting effect resolves against its own pick
        // rather than every effect reading the first one. The flat list
        // still goes along — ward, the stack display and every other
        // consumer read that (`RulesEngine.cast_spell`).
        act({ ...send, targets, target_groups: groups, x });
      } else {
        act({ ...send, targets, x });
      }
      // Submitted (or about to be, via `act`) — the backend drops any saved
      // draft as a side effect of the real action succeeding, but clear it
      // here too so a failed submission doesn't leave a stale one behind.
      persistCastTargetingDraft();
    } else {
      persistCastTargetingDraft();
      render();
    }
  }

  // --- Rendering helpers ------------------------------------------------

  // The battlefield, laid out in rows by card type (creatures / artifacts &
  // enchantments / lands). Attachments (Auras, Equipment — RULE 301/303) are
  // pulled out of the flow and drawn inside a dashed group box around the
  // permanent they're attached to, rather than as loose cards.
  function battlefieldHtml(objs, byInstance = {}, pending = null) {
    if (!objs.length) return `<p class="empty-state">${t('bd.bf.none')}</p>`;
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
      return `<div class="gf-attach-group" title="${escapeAttr(t('bd.bf.attachTitle'))}">${host}${attached}</div>`;
    };

    const rowHtml = (label, list) =>
      `<div class="gf-bf-row">
        <span class="gf-bf-row-label">${label} (${list.length})</span>
        ${list.length ? `<div class="card-grid">${list.map(renderObj).join('')}</div>` : '<p class="empty-state">–</p>'}
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
  function stackItemHtml(item, index, total, opts = {}) {
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
    const isTop = !opts.ghost && index === total - 1;
    // `opts.ghost` = a just-resolved entry lingering for a moment: no LIFO
    // position, just an "aufgelöst" caption.
    const orderText = opts.ghost
      ? t('bd.rail.stackResolved')
      : total > 1
        ? (isTop ? t('bd.stack.topResolves') : `#${total - index}`)
        : '';
    const order = orderText ? `<span class="gf-stack-order">${escapeHtml(orderText)}</span>` : '';
    const overlay = showOverlay
      ? `<div class="gf-stack-ability-overlay">${escapeHtml(abilityText)}</div>`
      : '';
    const link = showOverlay
      ? `<button type="button" class="gf-stack-source-link" data-hover-card="${escapeHtml(visual.name)}" title="Quelle: ${escapeHtml(visual.name)}">🔗</button>`
      : '';
    return `
      <div class="gf-card-slot gf-stack-item${isTop ? ' is-top' : ''}${opts.ghost ? ' gf-rail-stack-ghost' : ''}">
        <span class="gf-stack-badge gf-stack-badge--${badge.cls}">${badge.icon} ${escapeHtml(badge.label)}</span>
        <div class="${classes.join(' ')}" data-hover-card="${escapeHtml(displayName)}" title="${escapeHtml(displayName)}">
          ${inner}
          ${overlay}
          ${link}
        </div>
        ${order}
      </div>`;
  }

  // The per-priority countdown, as a shrinking progress bar in the rail.
  // Only for an interactive-priority session, only while this client holds
  // priority, and only when the server timer is > 0. The bar width is driven
  // by the `--gf-timer-frac` custom property, updated each second by
  // `paintCountdown()` without a full re-render.
  function railTimerHtml() {
    // Shown for the whole priority window this client holds (given a server
    // timer > 0), so interrupting it leaves a visibly *stopped* bar rather
    // than making the whole widget vanish. `paintCountdown()` keeps the
    // number + bar live from here; `autoPassArmed()` decides whether it is
    // actually running.
    if (!interactivePriority() || !hasPriority() || autoPassSeconds <= 0) return '';
    const s = view.state;
    if (s.game_over || s.pending_choice) return '';
    // A response clock: silent during your own main phases/combat — see
    // `reactTimerSuppressedHere`.
    if (reactTimerSuppressedHere()) return '';
    const off = autoPassCancelled;
    const shown = off ? Math.max(0, autoPassRemaining) : autoPassSeconds;
    const frac = off ? Math.max(0, autoPassRemaining) / autoPassSeconds : 1;
    return `
      <div class="gf-rail-timer${off ? ' gf-timer-off' : ''}">
        <div class="gf-rail-timer-head">
          <span>${escapeHtml(t('bd.rail.timerLabel'))}</span>
          <span><span data-timer-count>${shown}</span>s</span>
        </div>
        <div class="gf-rail-timer-track">
          <div class="gf-rail-timer-fill" data-timer-bar style="--gf-timer-frac: ${frac}"></div>
        </div>
        <button type="button" class="gf-rail-timer-stop" data-timer-interrupt ${off ? 'disabled' : ''}>${escapeHtml(t('bd.rail.timerInterrupt'))}</button>
      </div>`;
  }

  //: VIS-12: the steps a seat can be stopped at — the server's `STOP_STEPS`
  //: (`services/game_session.py`) — and the two that can't be unticked on your
  //: own turn (both main phases: that is where you act at all).
  const STOP_STEPS = [
    'upkeep', 'draw', 'main1', 'begin_combat', 'declare_attackers',
    'declare_blockers', 'combat_damage', 'end_combat', 'main2', 'end',
  ];
  const ALWAYS_STOP_OWN_TURN = ['main1', 'main2'];

  /** This seat's standing stops: the server's, else "everywhere". */
  function currentStops() {
    const seat = view?.perspective;
    return view?.priority?.stops?.[seat] || { own: [...STOP_STEPS], opponent: [...STOP_STEPS] };
  }

  /** Offer the saved stops to the server once per game (never over its own). */
  function syncStopsPref() {
    if (stopsSynced || busy || !interactivePriority() || !view.perspective) return;
    stopsSynced = true;
    if (view.priority.stops?.[view.perspective]) return;
    const pref = getStopsPref();
    if (pref) act({ type: 'set_stops', own: pref.own, opponent: pref.opponent });
  }

  // The stops panel, in the rail: for each step, whether *you* want to be
  // asked on your own turn / on everyone else's. A step without a stop is
  // passed for you when the stack is empty; anything another player puts on
  // the stack always reaches you regardless. A seat's armed yield is public
  // (`yieldBadgeHtml` on its banner), so the table sees who is passing.
  function railStopsHtml() {
    if (!interactivePriority() || !view.perspective || view.state.game_over) return '';
    const stops = currentStops();
    const rows = STOP_STEPS.map((step) => {
      const own = stops.own.includes(step);
      const opp = stops.opponent.includes(step);
      const locked = ALWAYS_STOP_OWN_TURN.includes(step);
      return `<tr>
        <td>${escapeHtml(STEP_LABELS[step] || step)}</td>
        <td><input type="checkbox" data-stop="own" data-step="${step}" ${own ? 'checked' : ''} ${locked || busy ? 'disabled' : ''}></td>
        <td><input type="checkbox" data-stop="opponent" data-step="${step}" ${opp ? 'checked' : ''} ${busy ? 'disabled' : ''}></td>
      </tr>`;
    }).join('');
    return `
      <details class="gf-rail-stops" data-stops-panel ${stopsPanelOpen ? 'open' : ''}>
        <summary>${escapeHtml(t('bd.rail.stopsHeading'))}</summary>
        <p class="gf-rail-stops-help">${escapeHtml(t('bd.rail.stopsHelp'))}</p>
        <table>
          <thead><tr><th></th><th>${escapeHtml(t('bd.rail.stopsOwn'))}</th><th>${escapeHtml(t('bd.rail.stopsOpponent'))}</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </details>`;
  }

  function wireStopsPanel() {
    const panel = root.querySelector('[data-stops-panel]');
    if (!panel) return;
    panel.addEventListener('toggle', () => { stopsPanelOpen = panel.open; });
    panel.querySelectorAll('input[data-stop]').forEach((box) => {
      box.addEventListener('change', () => {
        const next = { own: [], opponent: [] };
        panel.querySelectorAll('input[data-stop]:checked').forEach((c) => {
          next[c.dataset.stop].push(c.dataset.step);
        });
        setStopsPref(next);
        act({ type: 'set_stops', own: next.own, opponent: next.opponent });
      });
    });
  }

  // VIS-12 keyboard shortcuts, after Arena/MTGO: Space passes priority (Arena
  // Space / MTGO F2), Enter passes this (opponent's) turn (Arena Enter / MTGO
  // F4 — a yield that still stops for anything an opponent puts on the
  // stack), E skips to the end step of your own turn. Ignored while typing, with a modifier held, on a focused
  // control (it handles its own Enter/Space) and for a board that isn't the
  // one on screen (each tab keeps its own).
  function onShortcutKey(event) {
    if (!sessionId || !view || !root?.isConnected || root.offsetParent === null) return;
    if (!interactivePriority() || busy || view.state.game_over || view.state.pending_choice) return;
    if (event.ctrlKey || event.metaKey || event.altKey || event.repeat) return;
    const el = event.target;
    if (el instanceof Element && el.closest('input, textarea, select, button, a, summary, [contenteditable]')) return;
    if (document.querySelector('dialog[open]')) return;
    if (event.key === ' ') {
      if (!hasPriority()) return;
      event.preventDefault();
      act({ type: 'pass_priority' });
      return;
    }
    const ownTurn = view.state.active_player_id === actingSeat();
    const mode = event.key === 'Enter' ? 'turn' : event.key.toLowerCase() === 'e' ? 'end_step' : null;
    if (!mode || myYield() || (mode === 'turn') === ownTurn) return; // Enter: opponents' turns, E: yours
    if (mode === 'end_step' && view.state.current_step === 'end') return;
    event.preventDefault();
    act({ type: 'set_yield', mode });
  }
  document.addEventListener('keydown', onShortcutKey);

  // The stack, in the rail — always rendered (every mode), so it stays
  // visible what is going onto the stack. Each entry is a mini card view
  // (`stackItemHtml`): the spell's own card, or a triggered/activated
  // ability's source permanent with the ability text overlaid, plus a badge
  // saying which it is (Zauber / ausgelöste / aktivierte Fähigkeit) and its
  // LIFO position. Below the live entries sit the greyed-out ghosts of
  // entries that resolved in the last couple of seconds (`resolvedGhosts`).
  function railStackHtml(s) {
    const items = s.stack.map((it, i) => stackItemHtml(it, i, s.stack.length)).join('');
    const ghosts = resolvedGhosts
      .map((g) => stackItemHtml(g.item, 0, 1, { ghost: true }))
      .join('');
    const body = items || ghosts
      ? `<div class="gf-rail-stack-cards">${items}${ghosts}</div>`
      : `<p class="gf-rail-stack-empty">${escapeHtml(t('bd.rail.stackEmpty'))}</p>`;
    return `
      <div class="gf-rail-stack">
        <h4>${escapeHtml(t('bd.stack.heading', { count: s.stack.length }))}</h4>
        ${body}
      </div>`;
  }

  function stackKindBadge(item) {
    if (item.category === 'triggered_ability') {
      return { cls: 'triggered', icon: '⚡', label: t('bd.stack.triggered') };
    }
    if (item.category === 'activated_ability') {
      return { cls: 'activated', icon: '🔧', label: t('bd.stack.activated') };
    }
    return { cls: 'spell', icon: '🃏', label: spellTypeLabel(item.type_line) };
  }

  function spellTypeLabel(typeLine) {
    const tl = (typeLine || '').toLowerCase();
    // NB: match on `tl` (the lower-cased type line), not `t` (the i18n
    // function) — `t.includes(...)` threw `TypeError: t.includes is not a
    // function` for every non-creature spell, which bubbled out of
    // `render()` and, because `withBusy` renders before its try block, left
    // `busy` stuck true and every control disabled the moment a
    // non-creature spell hit the stack.
    if (tl.includes('creature')) return t('bd.stack.creatureSpell');
    if (tl.includes('instant')) return t('bd.stack.instantSpell');
    if (tl.includes('sorcery')) return t('bd.stack.sorcerySpell');
    if (tl.includes('planeswalker')) return t('bd.stack.planeswalkerSpell');
    if (tl.includes('artifact')) return t('bd.stack.artifactSpell');
    if (tl.includes('enchantment')) return t('bd.stack.enchantmentSpell');
    return t('bd.stack.genericSpell');
  }

  function zoneListHtml(objs, empty) {
    if (!objs.length) return `<p class="empty-state">${empty}</p>`;
    return `<ul class="gf-zone-list">${objs
      .map((o) => `<li data-hover-card="${escapeHtml(o.name)}">${escapeHtml(o.name)}</li>`)
      .join('')}</ul>`;
  }

  // A side-column zone (Friedhof / Exil) whose body collapses to just the
  // header by default (`expandedZones`), so a large graveyard can't stretch
  // the fixed-width column and shove the rest of the board around. An empty
  // zone shows its "leer" body outright with no toggle; a non-empty one
  // turns the header into a ▸/▾ button and height-caps the open body so it
  // scrolls inside itself rather than growing the layout. `bodyHtml` already
  // carries its own "leer" empty-state, so the count drives everything here.
  function collapsibleZoneHtml(cls, label, key, count, bodyHtml) {
    const empty = count === 0;
    if (empty) {
      return `<div class="gf-zone ${cls}"><h4>${escapeHtml(label)} (0) — <span class="gf-zone-empty">leer</span></h4></div>`;
    }
    const open = expandedZones.has(key);
    return `
      <div class="gf-zone ${cls}">
        <h4><button type="button" class="gf-zone-toggle" data-zone-toggle="${escapeAttr(key)}" aria-expanded="${open ? 'true' : 'false'}"><span class="gf-zone-caret">${open ? '▾' : '▸'}</span> ${escapeHtml(label)} (${count})</button></h4>
        <div class="gf-zone-body"${open ? '' : ' hidden'}>${bodyHtml}</div>
      </div>`;
  }

  // Whether this permanent's tile should currently show its *back* face —
  // its real transformed state (RULE 712.8), inverted by a client-only
  // "🔄 peek" toggle (`flippedForView`) that doesn't touch game state.
  function showsBackFace(o) {
    return flippedForView.has(o.instance_id) ? !o.transformed : !!o.transformed;
  }

  // Art URL for a game object: prefer the by-name `imageCache` (populated
  // from a deck import — see state.js, indexed under both the front *and*
  // back face names so a transformed permanent's now-current name still
  // hits it), but fall back to building the URL straight from the object's
  // own `card_id` (always present on non-tokens, see GameObject.to_dict) so
  // objects added directly in Replay/Puzzle mode (never resolved into
  // imageCache) still show art in Spielmodus.
  function resolveImageUrl(o, imageCache) {
    // RULE 701.20a: a card exiled face down (Beseech the Mirror) shows its
    // back, not its art — the one place the sleeve fallback below has a
    // real, reachable use today. Checked before the name cache so a card
    // whose art is already loaded doesn't leak through it.
    if (o.face_down_in_exile) return assetsSleeveImageUrl || null;
    // RULE 708.2: a face-down permanent (morph/disguise/manifest/cloak) is a
    // 2/2 with no identity at all — the backend already ships only the
    // synthetic face (`game/face_down.py`), so there is nothing to leak, but
    // there is also no art to show: render the player's card back. This is
    // the case the sleeve fallback below was written for before any state
    // could actually reach it.
    if (o.face_down) return assetsSleeveImageUrl || null;
    const showBack = showsBackFace(o);
    const isToken = o.is_token || (o.card_id || '').startsWith('token:');
    // Tokens first try an exact-id match: the same token *name* is reprinted
    // at different stat lines across Magic's history (several "Shapeshifter"
    // tokens exist as a 1/1, a 2/2, …), so a same-named-but-different-P/T
    // token in the same game needs its own art, not whichever variant's
    // entry happened to land last in the shared by-name cache below (see
    // `preloadDeckTokens`'s token-art seeding — it sets both keys).
    if (isToken && o.card_id) {
      const byId = imageCache?.get(o.card_id);
      if (byId) {
        if (showBack && byId.backSmall) return byId.backSmall;
        if (!showBack && byId.small) return byId.small;
      }
    }
    const cached = imageCache?.get((o.name || '').toLowerCase());
    if (cached) {
      if (showBack && cached.backSmall) return cached.backSmall;
      if (!showBack && cached.small) return cached.small;
    }
    if (isToken) {
      const custom = tokenImages[(o.name || '').toLowerCase()];
      if (custom) return custom;
      // A face-down/transformed token (e.g. a token copy of a flipped DFC,
      // RULE 707) has no real art for its back — fall back to the
      // player's chosen sleeve backside instead of a blank tile.
      if (showBack && assetsSleeveImageUrl) return assetsSleeveImageUrl;
      // No specific art for this token by name (typically an ad hoc token
      // an effect synthesized inline, e.g. "1/1 white Soldier", which has
      // no catalogue entry to upload art against by exact name) — the
      // player's "generic" token image (settings.js) covers all of these.
      return tokenImages[GENERIC_TOKEN_KEY] || null;
    }
    if (!o.card_id) return null;
    return cardImageUrl(o.card_id, 'small', showBack ? 'back' : 'front');
  }

  function objCard(o, imageCache, cardActions) {
    const imageUrl = resolveImageUrl(o, imageCache);
    const inner = imageUrl
      ? `<img src="${imageUrl}" alt="${escapeHtml(o.name)}" loading="lazy" />`
      : escapeHtml(o.name);
    const classes = ['card'];
    // RULE 302.6 only matters for a creature permanent on the battlefield.
    // A creature with Haste must never carry the visual marker.
    const hasHaste = (o.keywords || []).some((keyword) => keyword.toLowerCase() === 'haste');
    const isSummoningSick = o.zone === 'battlefield' && o.is_creature && o.summoning_sick && !hasHaste;
    if (imageUrl) classes.push('has-image');
    if (o.tapped) classes.push('tapped');
    if (isSummoningSick) classes.push('summoning-sick');
    if (o.attacking) classes.push('attacking');
    if (compactView) classes.push('compact-card');
    // RULE 115/601.2c: this object is the chosen target of something
    // currently on the stack — `updateTargetOverlays` (called once per
    // `render()`) reduces `s.stack[*].targets` to this instance-id set.
    if (targetedInstanceIds.has(o.instance_id)) classes.push('gf-targeted');
    // Two permanents each targeting the other (Fight-shaped abilities, or
    // two removal spells naming each other's source) get a distinct border
    // instead of just the plain target overlay, so the pairing itself reads
    // at a glance.
    if (mutualTargetPairIds.has(o.instance_id)) classes.push('gf-mutual-target');
    if (abilitySourceInstanceIds.has(o.instance_id)) classes.push('gf-ability-source');
    // "Mana-Potenzial": server-computed (`services/game_session.py`'s
    // `_annotate_castable`) — whether this hand card could be paid for by
    // tapping/exiling untapped mana sources, purely a mana-affordability
    // signal (it does *not* imply the play is otherwise legal right now —
    // timing/targets can still block it). A real "✨ Zaubern"/"⚡
    // Aktivieren" button, when `legal_actions` offers one, now silently
    // auto-taps exactly what's missing on click (`GameEngine.cast_spell`/
    // `activate_ability`'s own `_auto_tap_for_*_if_needed` hook) — so this
    // highlight is a preview of that, not a separate action to trigger.
    if (o.castable) classes.push('castable-highlight');
    const pt = o.power != null && o.toughness != null ? ` (${o.power}/${o.toughness})` : '';
    const hasBasePt = o.base_power != null && o.base_toughness != null;
    const ptChanged = o.power != null && o.toughness != null && hasBasePt
      && (o.power !== o.base_power || o.toughness !== o.base_toughness);
    const compactPt = compactView && o.zone === 'battlefield' && o.is_creature
      && o.power != null && o.toughness != null
      ? `<span class="gf-compact-pt${ptChanged ? ' is-changed' : ''}" title="${escapeAttr(`${o.power}/${o.toughness}`)}">${o.power}/${o.toughness}</span>`
      : '';
    const buttons = cardActionButtons(cardActions);
    const attackBadge = o.attacking
      ? `<span class="gf-attacking-badge">⚔️${o.combat_defender ? ` ${escapeHtml(o.combat_defender.label || '')}` : ''}</span>`
      : '';
    // RULE 302.6: only an actually restricted creature gets a badge. Inset in the
    // top-right corner (not an overhanging pill like the loyalty/battle/
    // attacking badges) so it never collides with them on a hasty attacker
    // that's still nominally summoning-sick.
    const summoningSickBadge = isSummoningSick
      ? `<span class="gf-sick-badge" title="${escapeAttr(t('bd.badge.summoningSickTitle'))}">💤</span>`
      : '';
    // RULE 115/601.2c: a 🎯 centered on the card for anything currently
    // targeted by a spell/ability on the stack (`gf-targeted` above already
    // drives the border/outline; this is the actual glyph).
    const targetOverlay = targetedInstanceIds.has(o.instance_id)
      ? `<span class="gf-target-overlay" title="${escapeAttr(t(mutualTargetPairIds.has(o.instance_id) ? 'bd.badge.mutualTargetTitle' : 'bd.badge.targetedTitle'))}">🎯</span>`
      : '';
    // RULE 606: a planeswalker's loyalty gets its own badge (mirrors the
    // ♦{loyalty} glyph on the Replay board editor) rather than being read
    // off the generic counter badge, which would otherwise show it twice
    // (`counters` also carries a "loyalty" key — GameObject.loyalty reads it).
    const loyaltyBadge = o.is_planeswalker && o.loyalty != null
      ? `<span class="gf-loyalty-badge">◆ ${o.loyalty}</span>`
      : '';
    // RULE 714: a Saga's chapter progress, mirroring the loyalty badge above
    // (and, like it, pulled out of the generic counter badge below so "lore"
    // doesn't show twice). `saga_final_chapter` is only set once the oracle
    // parser recognized at least one chapter line; without it, just the raw
    // lore count is shown (no "/N" to compare against).
    const lore = (o.counters || {}).lore;
    const sagaBadge = o.is_saga && lore != null
      ? `<span class="gf-loyalty-badge gf-saga-badge" title="${escapeAttr(t('bd.badge.sagaTitle'))}">📜 ${lore}${o.saga_final_chapter ? `/${o.saga_final_chapter}` : ''}</span>`
      : '';
    // RULE 310.4c: a battle's current defense is its defense-counter count,
    // badged like loyalty/lore above (and likewise pulled out of the generic
    // counter badge so "defense" doesn't show twice). RULE 310.8: the
    // protector is the player who defends it — shown by name, resolved
    // against the view's own player list, since a raw id means nothing here.
    const protectorName = o.protector_id ? playerName(o.protector_id) : null;
    const battleBadge = o.is_battle && o.defense != null
      ? `<span class="gf-loyalty-badge gf-battle-badge" title="${escapeAttr(t('bd.badge.battleTitle') + (protectorName ? t('bd.badge.battleProtectedBy', { name: protectorName }) : ''))}">🛡 ${o.defense}${protectorName ? ` · ${escapeHtml(protectorName)}` : ''}</span>`
      : '';
    const counterEntries = Object.entries(o.counters || {})
      .filter(([k]) => !(o.is_planeswalker && k === 'loyalty') && !(o.is_saga && k === 'lore')
        && !(o.is_battle && k === 'defense'));
    const counterBadge = counterEntries.length
      ? `<span class="gf-counter-badge">${counterEntries.map(([k, v]) => `${escapeHtml(k)}×${v}`).join(' · ')}</span>`
      : '';
    const keywordBadge = (o.keywords && o.keywords.length)
      ? `<span class="gf-keyword-badge" title="${escapeAttr(o.keywords.join(', '))}">${o.keywords.map((k) => escapeHtml(keywordAbbrev(k))).join(' ')}</span>`
      : '';
    // RULE 715.3d: an Adventure creature exiled by its own spell half,
    // castable from here — flags it distinctly from an inert exiled card.
    const adventureBadge = o.adventure_castable
      ? `<span class="gf-adventure-badge" title="${escapeAttr(t('bd.badge.adventureTitle'))}">${t('bd.badge.adventure')}</span>`
      : '';
    // RULE 722.3a: this permanent is prepared — its exiled prepare-spell
    // copy is castable (badged on that copy's own tile via `prepared_copy`
    // below, since that's a property of the copy, not of this permanent).
    const preparedBadge = o.prepared
      ? `<span class="gf-prepared-badge" title="${escapeAttr(t('bd.badge.preparedTitle'))}">${t('bd.badge.prepared')}</span>`
      : '';
    // RULE 722.3c: this *is* that exiled prepare-spell copy.
    const preparedCopyBadge = o.prepared_copy
      ? `<span class="gf-prepared-badge" title="${escapeAttr(t('bd.badge.preparedCopyTitle'))}">${t('bd.badge.preparedCopy')}</span>`
      : '';
    // RULE 708.2: a face-down permanent shows *what put it there* (morph,
    // disguise, manifest, cloak) and nothing about the card underneath —
    // which is all the payload carries anyway. The kind matters to the
    // player because it decides how it can be turned face up (RULE
    // 702.37e/701.40b) and whether it has ward {2} (RULE 702.168a/701.58a).
    const faceDownLabels = {
      morph: t('bd.faceDown.morph'), disguise: t('bd.faceDown.disguise'), manifest: t('bd.faceDown.manifest'), cloak: t('bd.faceDown.cloak'),
    };
    const faceDownBadge = o.face_down
      ? `<span class="gf-facedown-badge" title="${escapeAttr(t('bd.faceDown.title'))}">🎭 ${escapeHtml(faceDownLabels[o.face_down_kind] || t('bd.faceDown.default'))}</span>`
      : '';
    const effectsSummary = effectSummaryHtml(o);
    // A double-faced permanent (transform/modal DFC) gets a "🔄 peek other
    // face" button — purely a client-side preview (`flippedForView`), not
    // an actual transform (RULE 712.8 stays a real game action, offered
    // instead among `buttons` when the card's own ability allows it).
    const flipButton = o.has_back_face
      ? `<button type="button" class="gf-card-flip" data-flip-toggle="${o.instance_id}" title="Andere Seite ansehen" aria-label="Andere Seite ansehen">🔄</button>`
      : '';
    const draggable = cardActions && cardActions.some(isPlayableCardAction);
    const dragAttrs = draggable ? ` draggable="true" data-draggable-card="true"` : '';
    return `
      <div class="gf-card-slot" data-instance-id="${escapeAttr(o.instance_id)}">
        <div class="${classes.join(' ')}"${dragAttrs} data-hover-card="${escapeHtml(o.name)}" title="${escapeHtml(o.name)}${pt}${o.tapped ? escapeAttr(t('bd.tile.tapped')) : ''}"><span class="gf-card-art">${inner}${summoningSickBadge}${targetOverlay}</span>${flipButton}${attackBadge}${loyaltyBadge}${battleBadge}${counterBadge}${keywordBadge}${compactPt}${adventureBadge}${preparedBadge}${preparedCopyBadge}${faceDownBadge}${effectsSummary}</div>
        ${buttons}
      </div>`;
  }

  // Which exiled cards are castable from there right now, and why (RULE
  // 601.3b analogue / 715.3d / 722.3c) — the three independent mechanisms
  // `GameEngine._castable_from_exile`/`_has_temp_play_permission` check.
  // Returns ``null`` for an ordinary, inert exiled card.
  function exileCastableInfo(o, s) {
    if (o.adventure_castable) {
      return { reason: t('bd.exileCast.adventureReason'), duration: t('bd.exileCast.adventureDuration') };
    }
    if (o.prepared_copy) {
      return { reason: t('bd.exileCast.preparedReason'), duration: t('bd.exileCast.preparedDuration') };
    }
    const grantedTurn = s.temp_play_permissions ? s.temp_play_permissions[o.instance_id] : null;
    if (grantedTurn != null) {
      const source = s.temp_play_permission_source ? s.temp_play_permission_source[o.instance_id] : null;
      return {
        reason: source ? t('bd.exileCast.impulseReason', { source }) : t('bd.exileCast.tempReason'),
        duration: t('bd.exileCast.tempDuration', { turn: grantedTurn + 1 }),
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
        <h4>${escapeHtml(t('bd.exileCast.headingExile', { count: entries.length }))}</h4>
        <div class="card-grid gf-exile-castable-list">${cards}</div>
      </div>`;
  }

  // The graveyard sibling of `exileCastableHtml`: every card in this
  // player's graveyard that `legal_actions` currently offers a real
  // play/cast/activate for (Flashback, Escape, Disturb, Aftermath, "you may
  // cast … from your graveyard", …). The ordinary Friedhof zone lists these
  // too, but only by name and with no way to act on them — this callout is
  // where the actual buttons live, tile + art like the exile one.
  function graveCastableHtml(p, s, byInstance, pending) {
    if (pending) return '';
    const entries = (p.graveyard || []).filter(
      (o) => (byInstance[o.instance_id] || []).some(isPlayableCardAction),
    );
    if (!entries.length) return '';
    const imageCache = getState().imageCache;
    const cards = entries
      .map((o) => `
        <div class="gf-exile-castable-entry">
          ${objCard(o, imageCache, byInstance[o.instance_id] || [])}
        </div>`)
      .join('');
    return `
      <div class="gf-zone gf-exile-castable gf-grave-castable">
        <h4>${escapeHtml(t('bd.exileCast.headingGrave', { count: entries.length }))}</h4>
        <div class="card-grid gf-exile-castable-list">${cards}</div>
      </div>`;
  }

  // The hand and, *beside* it (not stacked above/below), the conditional
  // "spielbar aus dem Exil / Friedhof" callouts — they only take a column
  // of their own when at least one of them has something to show, otherwise
  // the hand spans the full width as before.
  function handAreaHtml(p, s, byInstance, pending, ownHand) {
    const aside = `${exileCastableHtml(p, s, byInstance, pending)}${graveCastableHtml(p, s, byInstance, pending)}`;
    const asideHtml = aside.trim()
      ? `<div class="gf-castable-aside">${aside}</div>`
      : '';
    return `
      <div class="gf-hand-area">
        <div class="gf-zone gf-hand">
          <h4>${t('bd.zone.hand')} (${p.hand_count != null ? p.hand_count : p.hand.length})${ownHand ? '' : opponentHandToggleHtml()}</h4>
          ${handHtml(p, byInstance, pending, ownHand)}
        </div>
        ${asideHtml}
      </div>`;
  }

  // The German label for a trace entry's `duration` (game/continuous.py):
  // how long the effect lasts, shown as a chip in the per-card summary.
  function durationLabel(d) {
    if (d === 'end_of_turn') return t('bd.dur.endOfTurn');
    if (d === 'permanent') return t('bd.dur.permanent');
    return t('bd.dur.static'); // "static": lasts while its source stays in play
  }

  function durationTitle(d) {
    if (d === 'end_of_turn') return t('bd.durTitle.endOfTurn');
    if (d === 'permanent') return t('bd.durTitle.permanent');
    return t('bd.durTitle.static');
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
      <button type="button" class="gf-effects-badge" popovertarget="${escapeAttr(popId)}" title="${escapeAttr(t('bd.eff.badgeTitle'))}">Σ</button>
      <div id="${escapeAttr(popId)}" popover class="gf-effects-pop">
        <div class="gf-eff-result">${escapeHtml(t('bd.eff.result', { parts: resultParts.join(' · ') || '—' }))}</div>
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
  // RULE 702.174a: the "cast, promising a gift to <opponent>" offer — one entry per opponent,
  // so the label names who receives it.
  function giftHint(a) {
    return a.gift_opponent_id
      ? escapeHtml(t('bd.cast.giftHint', { name: a.gift_opponent_name || a.gift_opponent_id }))
      : '';
  }

  function faceHint(a) {
    if (a.face === 'fuse') return t('bd.faceHint.fuse');
    // RULE 702.103: the Bestow cast is the same card name as the plain
    // creature cast, so it gets a short "(Bestow — <cost>)" suffix rather
    // than a redundant repeated name, the same treatment as Fuse above.
    if (a.face === 'bestow') {
      return a.bestow_cost_label ? ` (Bestow — ${escapeHtml(a.bestow_cost_label)})` : ' (Bestow)';
    }
    // RULE 702.37a/702.168a: the morph/disguise offer casts the card FACE
    // DOWN as a nameless 2/2 for its face-down cost ({3}) — a wholly
    // different play from the ordinary front-face cast (a separate button
    // with no `face`). Label it as such so the two aren't mistaken for a
    // redundant pair of "cast" buttons (which is exactly what
    // ` — <card name>` looked like).
    if (a.face === 'face_down') {
      const kind = a.face_down_kind ? t(`bd.faceDown.${a.face_down_kind}`) : t('bd.faceDown.default');
      return t('bd.faceHint.faceDown', { kind, cost: a.cost_label || '{3}' });
    }
    return a.face ? ` — ${escapeHtml(a.name)}` : '';
  }

  // RULE 700.2: a modal spell offers one `cast_spell` action per mode (or
  // per legal mode combination — `_modal_cast_actions`), each tagged with
  // `mode`/`mode_description`. Without this, every offered variant renders
  // as an identical "✨ Zaubern" button and `findTargetableAction` picks
  // whichever happens to come first in `legal_actions` — the player never
  // actually chooses a mode. `a.entwine` (RULE 702.42a) reuses the same
  // "both modes" `mode: "both"` shape, just priced, so it gets its own
  // label rather than falling back to the plain mode text.
  function modeHint(a) {
    if (!a.mode_description) return a.entwine ? t('bd.modeHint.entwine') : '';
    const suffix = a.entwine ? t('bd.modeHint.entwine') : '';
    return ` — ${escapeHtml(a.mode_description)}${suffix}`;
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
    const label = a.kicker_keyword === 'offspring' ? 'Offspring' : 'Kicker';
    const title = a.kicker_cost ? `${label} ${a.kicker_cost}` : label;
    const field = `<input type="number" min="0" max="${a.max_kicker}" value="0" title="${escapeAttr(title)}" data-kicker-input="${kickerKey(a.instance_id, a.face)}" />`;
    return field + kickerXFieldHtml(a);
  }

  // Kicker's own {X} (RULE 702.33b, PAR-7 — Emblazoned Golem's "Kicker {X}",
  // a separately-announced value from both the spell's own X and how many
  // times Kicker is paid); defaults to 0 like Kicker itself, for the same
  // "an optional cost increase, not paid by default" reason.
  function kickerXFieldHtml(a) {
    if (!a.kicker_has_x) return '';
    return `<input type="number" min="0" max="${a.kicker_max_x}" value="0" title="Kicker X" data-kicker-x-input="${kickerKey(a.instance_id, a.face)}" />`;
  }

  function cardActionButtons(cardActions) {
    if (!cardActions || !cardActions.length) return '';
    const buttons = [];
    for (const a of cardActions) {
      if (a.type === 'play_land') {
        buttons.push(
          actionButton(
            { type: 'play_land', instance_id: a.instance_id, name: a.name, face: a.face },
            t('bd.cast.playLand', { face: faceHint(a) })
          )
        );
      } else if (a.type === 'cast_spell' && a.locked) {
        const reason = a.lock_reason || t('bd.cast.noValidTarget');
        buttons.push(
          `<button type="button" class="gf-card-action gf-locked" disabled title="${escapeAttr(reason)}">🔒 ${escapeHtml(reason)}${faceHint(a)}</button>`
        );
      } else if (a.type === 'cast_spell' && a.requires_target) {
        buttons.push(castTargetHtml(a));
      } else if (a.type === 'cast_spell' && a.discard_cost) {
        // "As an additional cost to cast this spell, discard N cards" (RULE
        // 601.2b) — open the picker so the player chooses which cards pay it
        // (RULE 602.1), instead of the engine auto-discarding from the back
        // of the hand.
        const startInfo = JSON.stringify({
          iid: a.instance_id, face: a.face, mode: a.mode,
          evoke: a.evoke, surge: a.surge, blitz: a.blitz, pay_additional: a.pay_additional, bargained: a.bargained,
          gift_opponent_id: a.gift_opponent_id,
        });
        buttons.push(
          `<button type="button" class="gf-card-action" data-discard-choice-start='${escapeAttr(startInfo)}'>${escapeHtml(t(a.blitz != null ? 'bd.cast.blitzPlain' : a.surge ? 'bd.cast.surgePlain' : a.evoke ? 'bd.cast.evokePlain' : 'bd.cast.castPlain', { mode: a.blitz != null ? `${modeHint(a)} (${a.blitz_cost_label || a.cost_label})` : modeHint(a), hint: '', face: faceHint(a) }))}</button>`
        );
      } else if (a.type === 'cast_spell' && (a.has_x || a.has_kicker)) {
        const xField = a.has_x
          ? `<input type="number" min="${a.min_x || 0}" max="${a.max_x}" value="${a.max_x}" data-x-input="${xKey(a.instance_id, a.face, a.blitz)}" />`
          : '';
        const suffix = [
          a.has_x ? 'X' : null,
          a.has_kicker ? (a.kicker_keyword === 'offspring' ? 'Offspring' : 'Kicker') : null,
          a.pay_additional ? a.additional_cost_label || 'Zusatzkosten' : null,
          a.bargained ? 'Bargain' : null,
          a.gift_opponent_id ? t('bd.cast.giftSuffix', { name: a.gift_opponent_name || a.gift_opponent_id }) : null,
        ].filter(Boolean).join(', ');
        buttons.push(`
          <div class="gf-cast-x">
            ${xField}${kickerFieldHtml(a)}
            <button type="button" class="gf-card-action" data-cast-x='${escapeAttr(JSON.stringify({ iid: a.instance_id, face: a.face, mode: a.mode, entwine: a.entwine, evoke: a.evoke, surge: a.surge, blitz: a.blitz, pay_additional: a.pay_additional, bargained: a.bargained, gift_opponent_id: a.gift_opponent_id }))}'>${escapeHtml(t(a.blitz != null ? 'bd.cast.blitzSuffix' : a.surge ? 'bd.cast.surgeSuffix' : a.evoke ? 'bd.cast.evokeSuffix' : 'bd.cast.castSuffix', { suffix, mode: a.blitz != null ? `${modeHint(a)} (${a.blitz_cost_label || a.cost_label})` : modeHint(a), face: faceHint(a) }))}</button>
          </div>
        `);
      } else if (a.type === 'cast_spell') {
        const hint = a.base_cost && a.effective_cost && a.base_cost !== a.effective_cost
          ? ` 💰${escapeHtml(a.effective_cost)}`
          : '';
        buttons.push(
          actionButton(
            { type: 'cast_spell', instance_id: a.instance_id, name: a.name, face: a.face, mode: a.mode, entwine: a.entwine, evoke: a.evoke, surge: a.surge, blitz: a.blitz, pay_additional: a.pay_additional, bargained: a.bargained, gift_opponent_id: a.gift_opponent_id },
            t(a.blitz != null ? 'bd.cast.blitzPlain' : a.surge ? 'bd.cast.surgePlain' : a.evoke ? 'bd.cast.evokePlain' : 'bd.cast.castPlain', {
              mode: a.blitz != null ? `${modeHint(a)} (${a.blitz_cost_label || a.cost_label})` : modeHint(a),
              hint: `${hint}${a.pay_additional ? ` + ${a.additional_cost_label || 'Zusatzkosten'}` : ''}${a.bargained ? ' + Bargain' : ''}${giftHint(a)}`,
              face: faceHint(a),
            })
          )
        );
      } else if (a.type === 'activate_ability' && a.locked) {
        const reason = a.lock_reason || t('bd.cast.noValidTarget');
        buttons.push(
          `<button type="button" class="gf-card-action gf-locked" disabled title="${escapeAttr(reason)}">🔒 ${escapeHtml(reason)}</button>`
        );
      } else if (a.type === 'activate_ability' && a.requires_target) {
        buttons.push(castTargetHtml(a));
      } else if (a.type === 'activate_ability' && a.has_x) {
        buttons.push(`
          <div class="gf-cast-x">
            <input type="number" min="${a.min_x || 0}" max="${a.max_x}" value="${a.max_x}" data-x-input="${a.instance_id}" />
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
      } else if (a.type === 'activate_ability' && a.sacrifice_cost) {
        // Cost includes "Sacrifice a <type>" (RULE 602.1) — which permanent
        // pays it is the player's own choice, not an engine auto-pick.
        const startInfo = JSON.stringify({ iid: a.instance_id, type: 'activate_ability', ability_index: a.ability_index });
        buttons.push(
          `<button type="button" class="gf-card-action${loyaltyModifierClass(a.cost_label)}" data-sacrifice-choice-start='${escapeAttr(startInfo)}'>⚡ ${escapeHtml(a.cost_label || 'Aktivieren')}</button>`
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
        if (a.has_x) {
          // ENG-51: "Sacrifice X Goats: Add X mana of any one color"
          // (Springjack Pasture) — X is announced with the activation, so one
          // X field serves every colour button.
          const colorButtons = optsList.map((opt) => {
            const info = JSON.stringify({ iid: a.instance_id, ability_index: a.ability_index, option_index: opt.index });
            return `<button type="button" class="gf-card-action" data-tap-x='${escapeAttr(info)}'>⟳ ${escapeHtml(a.cost_label || '')} → X·${opt.label || '⟳'}</button>`;
          }).join('');
          buttons.push(`
            <div class="gf-cast-x">
              <input type="number" min="${a.min_x || 0}" max="${a.max_x}" value="${a.max_x}" data-x-input="${a.instance_id}" />
              ${colorButtons}
            </div>
          `);
          if (a.any_combination) buttons.push(colorSplitHtml(a, 'tap_for_mana'));
          continue;
        }
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
          } else if (a.sacrifice_cost) {
            // A "Sacrifice a <type>: Add …" mana ability (Ashnod's Altar-
            // shaped) — same cost choice as `tap_cost` above, just naming
            // what to sacrifice instead of what to tap.
            const startInfo = JSON.stringify({
              iid: a.instance_id, type: 'tap_for_mana',
              ability_index: a.ability_index, option_index: opt.index,
            });
            buttons.push(
              `<button type="button" class="gf-card-action" data-sacrifice-choice-start='${escapeAttr(startInfo)}'>${text}</button>`
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
      } else if (a.type === 'turn_face_up') {
        // RULE 116.2b: the special action of turning a face-down permanent
        // face up — one button per payable route (its morph/disguise cost,
        // or a manifested/cloaked creature card's own mana cost, RULE
        // 702.37e/702.168d/701.40b/701.58b). No stack, so the card is simply
        // revealed the moment this lands.
        buttons.push(
          actionButton(
            { type: 'turn_face_up', instance_id: a.instance_id, option_index: a.option_index },
            `🔎 Aufdecken (${escapeHtml(a.cost_label || '')})`
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
  // hand-zone `activate_hand_mana` one). The colour set itself comes from
  // `a.options` (one option per colour the ability actually prints) rather
  // than a hardcoded WUBRG list — a *restricted* combination ability (Vivi
  // Ornitier's own "any combination of {U} and/or {R}") only ever offers
  // its own printed subset here, same as the single-colour buttons above
  // already do; a bare "any combination of colours" (Flamebraider/Selvala)
  // still lists all five, since its own `options` already does too.
  function colorSplitHtml(a, kind) {
    const total = a.has_x ? 'x' : a.combination_total;
    const max = a.has_x ? a.max_x : a.combination_total;
    const label = a.has_x ? 'X' : a.combination_total;
    const colors = (a.options || [])
      .map((opt) => Object.keys(opt.mana || {})[0])
      .filter(Boolean);
    const inputs = colors
      .map(
        (c) =>
          `<label class="gf-split-color" title="${c}">${MANA_SYMBOL_EMOJI[c]}<input type="number" min="0" max="${max}" value="0" data-split-color="${c}" /></label>`
      )
      .join('');
    const actionInfo = JSON.stringify({ type: kind, instance_id: a.instance_id, ability_index: a.ability_index });
    return `
      <div class="gf-mana-split" data-split-total="${total}" data-split-action='${escapeAttr(actionInfo)}'>
        <span class="gf-split-hint">Farbkombination (${label}):</span>
        ${inputs}
        <button type="button" class="gf-card-action" data-split-confirm>${t('bd.split.generate')}</button>
      </div>`;
  }

  function castTargetHtml(a) {
    const iid = a.instance_id;
    const xField = a.has_x
      ? `<input type="number" min="${a.min_x || 0}" max="${a.max_x}" value="${a.max_x}" data-x-input="${xKey(iid, a.face, a.blitz)}" />`
      : '';
    const startInfo = JSON.stringify({
      iid, type: a.type, ability_index: a.ability_index, face: a.face,
      mode: a.mode, entwine: a.entwine, evoke: a.evoke, surge: a.surge, blitz: a.blitz, pay_additional: a.pay_additional,
      bargained: a.bargained, gift_opponent_id: a.gift_opponent_id,
    });
    const label = a.type === 'activate_ability'
      ? t('bd.cast.activateLabel', { cost: a.cost_label || t('bd.cast.activateDefault') })
      : `${t(a.blitz != null ? 'bd.cast.blitzLabel' : a.surge ? 'bd.cast.surgeLabel' : a.evoke ? 'bd.cast.evokeLabel' : 'bd.cast.castLabel', { mode: a.blitz != null ? `${modeHint(a)} (${a.blitz_cost_label || a.cost_label})` : modeHint(a), face: faceHint(a) })}${a.pay_additional ? ` + ${a.additional_cost_label || 'Zusatzkosten'}` : ''}${a.bargained ? ' + Bargain' : ''}${giftHint(a)}`;
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
    if (castTargeting.excludePicked || req.distinct_from_others) {
      // A "tap N untapped <type>s you control" cost (RULE 602.1): the same
      // permanent can't pay two of the N picks. `distinct_from_others` is
      // RULE 109.5's "**another** target creature" (Pit Fight, Ulvenwald
      // Tracker) — same exclusion, but across *requirements*: whatever the
      // other half of the clause already chose is off this round's pool.
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
    // A cost *choice* (RULE 602.1: tap N / sacrifice / discard for a cost),
    // not a RULE 115 target — different heading and glyph from "Ziel wählen".
    const isDiscardChoice = castTargeting.isDiscardChoice;
    const isCostChoice = castTargeting.isTapChoice || castTargeting.isSacrificeChoice || isDiscardChoice;
    const modalGlyph = isDiscardChoice ? '🗑️' : (castTargeting.isTapChoice ? '⟳' : (castTargeting.isSacrificeChoice ? '💀' : '🎯'));
    const buttons = options.map((o) => {
      const payload = JSON.stringify({
        instance_id: iid, target: targetOptionPayload(o), controller_id: o.controller_id ?? null,
      });
      const hover = o.instance_id != null ? ` data-hover-card="${escapeHtml(o.name || '')}"` : '';
      return `<button type="button"${hover} data-cast-target-pick='${escapeAttr(payload)}'>${modalGlyph} ${escapeHtml(o.name)}</button>`;
    });
    if (req.optional) {
      const skip = JSON.stringify({ instance_id: iid, target: null });
      buttons.push(`<button type="button" class="gf-decline" data-cast-target-pick='${escapeAttr(skip)}'>${t('bd.cast.noTarget')}</button>`);
    }
    const heading = isCostChoice ? t('bd.cast.payCosts') : t('bd.cast.chooseTarget');
    const progress = total > 1 ? t('bd.cast.progress', { i: idx + 1, total }) : (isCostChoice ? t('bd.cast.select') : t('bd.cast.chooseTarget'));
    return `
      <div class="gf-modal-overlay">
        <div class="gf-modal gf-target-modal" role="dialog" aria-modal="true">
          <div class="gf-modal-head">
            <span class="gf-modal-icon">${modalGlyph}</span>
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
    const attackAction = (defender, index) => ({
      type: 'declare_attackers', instance_ids: [iid],
      ...(defender ? { defender: defenderPayload(defender) } : {}),
      attack_tax_amount: a.attack_tax_amounts?.[index] || 0,
      name: a.name,
    });
    if (defenders.length === 0) {
      return actionButton(
        attackAction(null, 0),
        '⚔️ Angreifen'
      );
    }
    if (defenders.length === 1) {
      const d = defenders[0];
      return actionButton(
        attackAction(d, 0),
        `⚔️ Angreifen → ${escapeHtml(d.label)}`
      );
    }
    const open = attackMenuOpen.has(iid);
    const menu = open
      ? `<div class="gf-attack-defenders">${defenders
          .map((d, index) =>
            actionButton(
              attackAction(d, index),
              `→ ${escapeHtml(d.label)}`
            )
          )
          .join('')}</div>`
      : '';
    return `<button type="button" class="gf-card-action" data-attack-toggle="${iid}">⚔️ Angreifen ${open ? '▴' : '▾'}</button>${menu}`;
  }

  // A defender spec from `legal_defenders_for` → the payload `declare_
  // attackers` validates against. The two permanent kinds (planeswalker,
  // RULE 508.1a; battle, RULE 310.5) are keyed by instance_id, a player by
  // id — so branch on *which key the spec carries* rather than listing the
  // permanent kinds, which is what silently mis-sent a battle as a player
  // when the "battle" kind was added server-side.
  function defenderPayload(d) {
    return d.instance_id != null
      ? { kind: d.kind, instance_id: d.instance_id }
      : { kind: 'player', id: d.id };
  }

  function actionButton(action, label, extraClass = '') {
    return `<button type="button" class="gf-card-action${extraClass}" data-action='${escapeAttr(JSON.stringify(action))}'>${label}</button>`;
  }

  // The passive "goldfish" opponent: a compact strip with its life (the
  // thing you're racing down), plus hidden hand/graveyard/library counts.
  function opponentStripHtml(opp) {
    return `
      <div class="gf-opponent" data-player-id="${escapeAttr(opp.id)}">
        <span class="gf-opp-name">🐟 ${escapeHtml(opp.name)}</span>
        <span class="gf-opp-life" title="${escapeAttr(t('bd.opp.lifeTitle'))}">❤️ ${opp.life}</span>
        ${commanderDamageHtml(opp.commander_damage)}
        <span title="${escapeAttr(t('bd.opp.handTitle'))}">🖐️ ${opp.hand_count ?? opp.hand?.length ?? 0}</span>
        <span title="${escapeAttr(t('bd.opp.graveTitle'))}">⚰️ ${opp.graveyard?.length ?? 0}</span>
        <span title="${escapeAttr(t('bd.opp.libraryTitle'))}">📚 ${opp.library_count ?? 0}</span>
        <span class="gf-opp-tag">${t('bd.opp.passive')}</span>
      </div>`;
  }

  // Everything about a *player* that isn't life or floating mana: poison
  // (RULE 704.5c), commander damage (RULE 903.10a), the counter bag
  // (RULE 122 energy, experience, rad, …), the Ring (RULE 701.51) and the
  // two designations (RULE 725/726). All of it is already in the payload
  // (`Player.to_dict`/`GameState.to_dict`) and was simply never drawn.
  function playerCountersHtml(p, s) {
    const bits = [];
    const poison = p.poison || 0;
    if (poison > 0) {
      // RULE 704.5c: ten poison counters and that player loses.
      bits.push(
        `<span class="gf-pcounter${poison >= 10 ? ' gf-pcounter--lethal' : ''}" title="Giftmarken (Regel 704.5c: 10 = verloren)">☠️ ${poison}/10</span>`,
      );
    }
    for (const [kind, amount] of Object.entries(p.counters || {})) {
      if (!amount) continue;
      bits.push(
        `<span class="gf-pcounter" title="${escapeAttr(counterLabel(kind))}">${counterIcon(kind)} ${amount}</span>`,
      );
    }
    if (p.ring_level > 0) {
      // RULE 701.52: the Ring tempts you — four cumulative levels.
      bits.push(
        `<span class="gf-pcounter" title="${escapeAttr(t('bd.ring.title', { level: p.ring_level }))}">💍 ${p.ring_level}/4</span>`,
      );
    }
    if (s.monarch_id === p.id) {
      bits.push(`<span class="gf-pcounter gf-pcounter--designation" title="${escapeAttr(t('bd.monarch.title'))}">${t('bd.monarch.label')}</span>`);
    }
    if (s.initiative_id === p.id) {
      bits.push(`<span class="gf-pcounter gf-pcounter--designation" title="${escapeAttr(t('bd.initiative.title'))}">⚔️ Initiative</span>`);
    }
    if (p.has_city_blessing) {
      // RULE 702.131c: no shared holder, unlike Monarch/Initiative above —
      // every player who has ascended shows this, any number at once.
      bits.push(`<span class="gf-pcounter gf-pcounter--designation" title="${escapeAttr(t('bd.cityBlessing.title'))}">${t('bd.cityBlessing.label')}</span>`);
    }
    // RULE 309: the dungeon card in this player's command zone, with the
    // room their venture marker is on and how far through they are — plus
    // every dungeon they have already completed (309.7), which is a real
    // card condition ("if you've completed a dungeon") and invisible
    // otherwise, since a completed dungeon leaves the game.
    if (p.dungeon) {
      const rooms = p.dungeon.rooms || [];
      const index = rooms.findIndex((r) => r.name === p.dungeon.current_room);
      const room = index >= 0 ? rooms[index] : null;
      const title = `${p.dungeon.name} (Regel 309) — Raum ${index + 1}/${rooms.length}${room ? `: ${room.effect_text}` : ''}`;
      bits.push(
        `<span class="gf-pcounter gf-pcounter--designation" title="${escapeAttr(title)}">🗝️ ${escapeHtml(p.dungeon.current_room || p.dungeon.name)}</span>`,
      );
    }
    if ((p.completed_dungeons || []).length) {
      bits.push(
        `<span class="gf-pcounter" title="${escapeAttr(t('bd.dungeon.completedTitle', { list: p.completed_dungeons.join(', ') }))}">🏁 ${p.completed_dungeons.length}</span>`,
      );
    }
    // RULE 902.2: a Vanguard avatar sits in the command zone all game with
    // its abilities functioning from there (902.4).
    if (p.vanguard) {
      bits.push(
        `<span class="gf-pcounter gf-pcounter--designation" title="${escapeAttr(`Vanguard-Avatar (Regel 902): ${p.vanguard.name}`)}">🧝 ${escapeHtml(p.vanguard.name)}</span>`,
      );
    }
    // RULE 904: the archenemy's scheme deck, and any ongoing scheme still
    // face up (904.9).
    if (s.archenemy_id === p.id || (p.scheme_deck_count || 0) > 0) {
      bits.push(
        `<span class="gf-pcounter gf-pcounter--designation" title="Erzfeind (Regel 904): Machenschaften im Stapel">😈 ${p.scheme_deck_count || 0}</span>`,
      );
    }
    for (const scheme of p.ongoing_schemes || []) {
      bits.push(
        `<span class="gf-pcounter" title="${escapeAttr(`Andauernde Machenschaft (Regel 904.9): ${scheme.name}`)}">📜 ${escapeHtml(scheme.name)}</span>`,
      );
    }
    const emblems = p.emblems || [];
    if (emblems.length) {
      const titles = emblems.map((e) => e.description || '').join(' · ');
      bits.push(
        `<span class="gf-pcounter" title="${escapeAttr(`Embleme (Regel 114): ${titles}`)}">🎖️ ${emblems.length}</span>`,
      );
    }
    const cmd = commanderDamageHtml(p.commander_damage);
    if (!bits.length && !cmd) return '';
    return `<div class="gf-pcounters">${bits.join('')}${cmd}</div>`;
  }

  // The counter bag is open-ended (any `add_player_counter` name), so this
  // is a nicety for the ones real cards produce, not a whitelist.
  const PLAYER_COUNTER_ICONS = {
    energy: '⚡', experience: '✨', rad: '☢️', ticket: '🎟️', acorn: '🌰',
  };
  const PLAYER_COUNTER_LABELS = {
    energy: t('bd.counter.energy'),
    experience: t('bd.counter.experience'),
    rad: t('bd.counter.rad'),
  };
  function counterIcon(kind) {
    return PLAYER_COUNTER_ICONS[kind] || '🔘';
  }
  function counterLabel(kind) {
    return PLAYER_COUNTER_LABELS[kind] || t('bd.counter.generic', { kind });
  }

  function commanderDamageHtml(commanderDamage) {
    const entries = Object.values(commanderDamage || {});
    if (!entries.length) return '';
    return entries
      .map((e) => {
        const lethal = e.amount >= 21 ? ' gf-cmd-dmg--lethal' : '';
        return `<span class="gf-cmd-dmg${lethal}" title="${escapeAttr(t('bd.cmdDmg.title', { name: e.name }))}">👑 ${e.amount}/21</span>`;
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
        ? t('bd.gameOver.won')
        : escapeHtml(t('bd.gameOver.lost', { name: winner.name }))
      : t('bd.gameOver.plain');
    return `<p class="server-status ${youWon ? 'ok' : 'warning'}">${banner}</p>`;
  }

  function manaPoolHtml(pool) {
    const order = ['W', 'U', 'B', 'R', 'G', 'C'];
    const parts = order.filter((c) => pool[c] > 0).map((c) => `<span class="gf-mana">${MANA_SYMBOL_EMOJI[c]}${pool[c]}</span>`);
    const restrictedParts = restrictedManaHtml(pool.restricted, MANA_SYMBOL_EMOJI, order);
    const empty = !parts.length && !restrictedParts.length;
    return `<div class="gf-manapool" title="${escapeAttr(t('bd.mana.poolTitle'))}">${empty ? `<span class="empty-state">${t('bd.mana.noMana')}</span>` : parts.join('') + restrictedParts.join('')}</div>`;
  }

  // "Mana-Potenzial": the maximum mana and coherent source-choice
  // variations from this player's untapped/unexiled sources. ``potential``
  // is `view.mana_potential[player_id]`
  // (absent for a seat this view doesn't own — RULE 400.2, same as the
  // hand array itself).
  function manaPotentialHtml(potential) {
    if (!potential) return '';
    const order = ['W', 'U', 'B', 'R', 'G', 'C'];
    const manaParts = (amounts) => order
      .filter((c) => amounts?.[c] > 0)
      .map((c) => `<span class="gf-mana">${MANA_SYMBOL_EMOJI[c]}${amounts[c]}</span>`)
      .join('');
    const variations = (potential.variations || [])
      .map((variation) => `
        <li class="gf-mana-potential-variation">
          <strong>${variation.total}</strong>${manaParts(variation.mana || {})}
        </li>`)
      .join('');
    const details = variations
      ? `<div class="gf-mana-potential-heading">${escapeHtml(t('bd.mana.variations'))}</div><ul>${variations}</ul>`
      : '';
    return `
      <details class="gf-mana-potential" title="${escapeAttr(t('bd.mana.potentialTitle'))}">
        <summary><span class="gf-mana-potential-label">${escapeHtml(t('bd.mana.maximum'))}</span><strong>${Number(potential.maximum || 0)}</strong></summary>
        <div class="gf-mana-potential-details">${details}</div>
      </details>`;
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
      return `<span class="gf-mana gf-mana-restricted" title="${escapeAttr(t('bd.mana.restrictedTitle', { label: restrictionLabel(lot.restriction) }))}">🔒${amounts}</span>`;
    });
  }

  // Human label for an opaque restriction dict (`game/mana_abilities.py`'s
  // `_parse_restriction` whitelist — this module has no server-side label
  // string to read, unlike `TargetSpec.label()` for targets, so the mapping
  // lives here).
  function restrictionLabel(restriction) {
    const kind = restriction?.kind;
    if (kind === 'contains_x') return t('bd.restrict.containsX');
    if (kind === 'creature_spell') {
      return restriction.allow_ability
        ? t('bd.restrict.creatureSpellAbility')
        : t('bd.restrict.creatureSpell');
    }
    if (kind === 'commander_spell') return t('bd.restrict.commanderSpell');
    if (kind === 'legendary_spell') return t('bd.restrict.legendarySpell');
    if (kind === 'instant_or_sorcery_spell') return t('bd.restrict.instantSorcery');
    if (kind === 'type_spell') {
      const types = (restriction.types || []).join('/');
      return restriction.allow_ability
        ? t('bd.restrict.typeSpellAbility', { types })
        : t('bd.restrict.typeSpell', { types });
    }
    return 'zweckgebunden';
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
        const label = dt.description || (visual ? visual.name : t('bd.stack.triggered'));
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
      return t('bd.delayed.whenAny', { step: stepLabel });
    }
    return t('bd.delayed.whenPlayer', { name: playerName(dt.controller_id), step: stepLabel });
  }

  function staticEffectsPanelHtml(view, s) {
    const actives = view.static_effects || [];
    const traced = (s.battlefield || []).filter((o) => (o.static_trace || []).length);
    const reductions = collectCostReductions(view.legal_actions || []);
    if (!actives.length && !traced.length && !reductions.length) {
      return `<div class="gf-statics"><h4>${t('bd.statics.panelHeading')}</h4>
        <p class="empty-state">Zurzeit keine statischen Effekte im Spiel.</p></div>`;
    }
    const layerLabel = (l) => (l === 'cost' ? 'Kosten (601.2f)' : `Layer ${l}`);
    // A continuous effect's two *bounds* (Regel 611 duration, Regel 613.6
    // "solange"-Bedingung) are shown next to what it does — an effect that
    // ends at end of combat, or that is currently switched off because its
    // condition doesn't hold, is otherwise indistinguishable on the board
    // from a permanent one. `gf-static-off` dims the second case rather than
    // hiding it: the ability really is in play and will apply again.
    const boundsHtml = (e) => {
      const bits = [];
      if (e.duration) bits.push(`<span class="gf-static-duration">⏳ ${escapeHtml(e.duration)}</span>`);
      if (e.condition) bits.push(`<span class="gf-static-condition">❓ ${escapeHtml(e.condition)}</span>`);
      if (e.condition && e.active === false) bits.push('<span class="gf-static-inactive">inaktiv</span>');
      return bits.join(' ');
    };
    const activeList = actives.length
      ? `<ul class="gf-static-list">${actives
          .map((e) =>
            `<li class="${e.active === false ? 'gf-static-off' : ''}">
             <span class="gf-static-layer">${escapeHtml(layerLabel(e.layer))}</span>
             <strong>${escapeHtml(e.source)}</strong> — ${escapeHtml(e.description || '')}
             <span class="gf-static-scope">(${escapeHtml(e.affects)})</span>
             ${boundsHtml(e)}</li>`
          )
          .join('')}</ul>`
      : `<p class="empty-state">${t('bd.statics.none')}</p>`;

    const traceBlocks = traced
      .map((o) => {
        const steps = (o.static_trace || [])
          .map((t) => {
            const pt = t.power != null && t.toughness != null ? ` → ${t.power}/${t.toughness}` : '';
            // A numeric layer is a real RULE 613 layer ("L6"); a string one is
            // a non-613 bucket (combat restrictions) that names itself.
            const layer =
              typeof t.layer === 'number' ? `L${t.layer}` : escapeHtml(String(t.layer));
            return `<li><span class="gf-static-layer">${layer}</span>
              ${escapeHtml(t.source)}: ${escapeHtml(t.description)}${escapeHtml(pt)}</li>`;
          })
          .join('');
        const pt = o.power != null && o.toughness != null ? t('bd.static.nowPt', { pt: `${o.power}/${o.toughness}` }) : '';
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
        <h4>${t('bd.statics.panelHeading')}</h4>
        <div class="gf-static-active"><h5>${t('bd.statics.activeHeading')}</h5>${activeList}</div>
        ${traceBlocks ? `<div class="gf-static-traces"><h5>${t('bd.statics.layerHeading')}</h5>${traceBlocks}</div>` : ''}
        ${costBlock}
      </div>`;
  }

  function collectCostReductions(actions) {
    return actions
      .filter((a) => a.type === 'cast_spell' && a.base_cost && a.effective_cost && a.base_cost !== a.effective_cost)
      .map((a) => ({ name: a.name, base: a.base_cost, effective: a.effective_cost }));
  }

  function statusHtml() {
    if (!status || statusKind === 'warning') return '';
    return `<p class="server-status ${statusKind}">${escapeHtml(status)}</p>`;
  }

  function lifeBox(label, life) {
    return `<div class="gf-life"><span class="gf-life-label">${escapeHtml(label)}</span><span class="life-total">${life}</span></div>`;
  }

  /** Detach: stop the auto-pass countdown and forget the session.
   *
   * A caller that navigates away from a live board (leaving a multiplayer
   * table) must call this — the countdown is an interval, and it would
   * otherwise keep ticking against a game this client is no longer in.
   */
  function stop() {
    stopAutoPass();
    autoPassWindowKey = null;
    sessionId = null;
    if (root) delete root.dataset.bugReportSession;
    view = null;
    resolvedGhosts = [];
    stopped = true;
  }

  return { mount, start, refresh, setAssets, stop };
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str == null ? '' : String(str);
  return div.innerHTML;
}

function escapeAttr(str) {
  return String(str).replace(/'/g, '&#39;').replace(/"/g, '&quot;');
}
