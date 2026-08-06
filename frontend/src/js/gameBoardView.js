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
import { bannerColorLabel, bannerGradients, bannerStyle } from './bannerColors.js';
import { MANA_SYMBOL_EMOJI } from './cardTile.js';
import {
  getAutoPassEnabled,
  getAutoPassScope,
  getAutoPassSeconds,
  getAutoSkipEmpty,
  getBotSpeedMs,
  getShowOpponentHand,
  saveSettings,
  BOT_SPEED_MS_OPTIONS,
  MAX_AUTO_PASS_SECONDS,
  MIN_AUTO_PASS_SECONDS,
} from './settings.js';

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
  land_tapped: '💧', land_tapped_reveal: '💧', order_triggers: '🔀', trigger_target: '🎯',
  enter_as_copy: '🪞', counter_unless_pays: '🚫', ward: '🛡️',
  commander_zone: '👑', trigger_mode: '🎭', add_mana_any_color: '💎',
  choose_creature_type: '🐾', choose_color: '🎨', choose_basic_land_type: '🗺️', read_ahead: '📜',
  scry: '🔮', surveil: '🕵️', opening_hand_battlefield: '🌅',
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
  // The stack overlays the board while non-empty; can be pushed aside to a
  // compact corner card so priority actions can be taken on the board below.
  let stackAside = false;
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
  // Double-faced permanents a player has clicked "🔄" on to *preview* the
  // other face — purely a client-side view toggle (RULE 712 has no such
  // concept; the object's real `transformed` state is untouched), so a
  // player can check a flip-card's back before it actually transforms, or
  // just look at the back of an already-transformed one. Keyed by
  // instance_id, same shape as `attackMenuOpen`.
  const flippedForView = new Set();
  // --- Auto-pass (RULE 117, shared games) ---------------------------------
  // When this client holds priority, a countdown runs and passes for them
  // when it reaches zero, so a game where nobody wants to respond doesn't
  // need two clicks per step. Deliberately *not* a silent auto-pass: the
  // remaining seconds are shown, and any interaction with the board cancels
  // the window (you're clearly still thinking), so it can't pass out from
  // under someone mid-decision.
  let autoPassSeconds = getAutoPassSeconds();
  let autoPassTimer = null;
  let autoPassRemaining = 0;
  //: Set once the player touches the board during a priority window; the
  //: countdown doesn't restart until they next *gain* priority.
  let autoPassCancelled = false;
  //: Which priority window the current countdown belongs to, so a repaint
  //: that doesn't change whose turn it is doesn't restart the clock.
  let autoPassWindowKey = null;

  // --- "Skip to the next real decision" (#2) ------------------------------
  //: Armed by the ⏭ button (one burst) or by the persisted checkbox
  //: (always). While armed, a priority window that offers *nothing but*
  //: `pass_priority` is passed straight through — no countdown, since
  //: there is by definition nothing to interrupt. Disarms the moment a
  //: real option shows up, so the burst stops where a decision starts.
  let skipBurstArmed = false;
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

  /** Whether an empty priority window should be passed through right now. */
  function skipEmptyArmed() {
    if (!skipBurstArmed && !getAutoSkipEmpty()) return false;
    if (!interactivePriority() || !hasPriority()) return false;
    const s = view.state;
    if (s.game_over || s.pending_choice || busy) return false;
    return !hasMeaningfulAction();
  }

  /** Whether the countdown should be running right now. */
  function autoPassArmed() {
    if (!getAutoPassEnabled() || autoPassCancelled) return false;
    if (!interactivePriority() || !hasPriority()) return false;
    const s = view.state;
    if (s.game_over || s.pending_choice || busy) return false;
    // Scope: by default the timer only runs when you're *responding* in
    // someone else's turn, which is what auto-pass means everywhere else in
    // Magic. Your own turn stays yours unless you asked for "always".
    if (getAutoPassScope() !== 'always' && s.active_player_id === view.perspective) return false;
    return true;
  }

  /** A key identifying the current priority window (see `autoPassWindowKey`). */
  function priorityWindowKey() {
    const s = view?.state;
    if (!s) return null;
    return [
      s.turn_number,
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

  /** (Re)start the countdown if this is a new window and it's armed. */
  function syncAutoPass() {
    const windowKey = priorityWindowKey();
    // Skipping wins over the countdown: a window with no options at all
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
    // A real decision (or the end of the game) ends the burst — the point
    // of ⏭ is to stop exactly here.
    if (skipBurstArmed && (hasMeaningfulAction() || view?.state?.game_over)) {
      skipBurstArmed = false;
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

  // Repaint just the number, not the board — a full re-render every second
  // would tear down and rebuild every card tile under the player's cursor.
  function paintCountdown() {
    root?.querySelectorAll('[data-autopass-count]').forEach((el) => {
      el.textContent = String(Math.max(0, autoPassRemaining));
    });
  }

  /** The player is doing something — don't pass out from under them. */
  function cancelAutoPassForThisWindow() {
    if (autoPassTimer === null && !autoPassCancelled) return;
    autoPassCancelled = true;
    // Touching the board is also a "stop skipping" signal — the player is
    // clearly looking at something.
    skipBurstArmed = false;
    stopAutoPass();
    root?.querySelectorAll('[data-autopass-count]').forEach((el) => {
      el.closest('.gf-priority-badge')?.classList.add('gf-autopass-off');
    });
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
  // VIS-5: a short-lived feed of the opponent's most recent moves ("Bob hat
  // X gespielt"), newest last — built off the exact same "did move_log
  // actually grow" signal above, so a reconnect rebroadcast of the same
  // committed position never spams it. Solo modes (`view.perspective` is
  // null — nobody else to report on) never populate it.
  let moveFeed = [];
  const MOVE_FEED_LIFETIME_MS = 6000;
  const MOVE_FEED_MAX_ITEMS = 3;
  // VIS-7: how long to wait between revealing consecutive new move-log
  // entries from the same view (almost always a bot's whole batched turn —
  // see `run_bots`/`_after_move` in api/multiplayer.py, which answer a bot
  // to completion before ever broadcasting) — 0 reproduces the old
  // "all at once" behaviour. Adjustable live via `botSpeedControlHtml`.
  let botSpeedMs = getBotSpeedMs();
  // Guards a staggered `pushMoveFeed` callback from firing into a board
  // that has since been torn down (`stop()`) — a `setTimeout` outlives the
  // view switch that scheduled it.
  let stopped = false;

  function pushMoveFeed(text) {
    const key = `${Date.now()}-${Math.random()}`;
    moveFeed = [...moveFeed.slice(-(MOVE_FEED_MAX_ITEMS - 1)), { key, text }];
    setTimeout(() => {
      moveFeed = moveFeed.filter((entry) => entry.key !== key);
      render();
    }, MOVE_FEED_LIFETIME_MS);
  }

  // Turns a raw `move_log` label ("cast_spell: Lightning Bolt",
  // "pass_priority", "declare_attackers") into a short German verb phrase.
  // Anything not in the table falls back to the raw label — same as the
  // "Verlauf" panel already shows it, just prefixed by who did it.
  function describeMoveLabel(label) {
    const sep = label.indexOf(': ');
    const kind = sep === -1 ? label : label.slice(0, sep);
    const name = sep === -1 ? '' : label.slice(sep + 2);
    const templates = {
      play_land: `hat ${name || 'ein Land'} gespielt`,
      cast_spell: `hat ${name || 'einen Zauberspruch'} gewirkt`,
      activate_ability: `hat eine Fähigkeit${name ? ` von ${name}` : ''} aktiviert`,
      pass_priority: 'hat gepasst',
      declare_attackers: 'hat Angreifer erklärt',
      declare_blockers: 'hat Blocker erklärt',
      keep_hand: 'hat die Starthand behalten',
      mulligan: 'hat einen Mulligan genommen',
    };
    if (kind === 'concede' || kind.startsWith('concede:')) return 'hat aufgegeben';
    return templates[kind] || `hat "${label}" gespielt`;
  }
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
  function expandMultiTargetRequirements(requirements) {
    const expanded = [];
    const owners = [];
    let excludePicked = false;
    let excludeControllers = false;
    for (const [reqIndex, req] of requirements.entries()) {
      const count = req.count || 1;
      if (count > 1) excludePicked = true;
      if (req.distinct_controllers) excludeControllers = true;
      for (let i = 0; i < count; i += 1) {
        expanded.push(req);
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

  /** Begin driving `sessionId`, rendering `initialView` immediately. */
  function start(sid, initialView) {
    sessionId = sid;
    stopped = false;
    applyView(initialView);
    restoreUiDraft(initialView);
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
    // VIS-5: feed the opponent's newest moves in on the same "move_log
    // actually grew" signal above (never on a reconnect rebroadcast of the
    // unchanged position, and never across a session switch).
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
      // VIS-7: stagger a batch of 2+ new entries (almost always a bot's
      // whole turn, run to completion before the single broadcast that
      // carries it — see `run_bots` in services/bots.py) instead of
      // revealing them all in the same tick. Offset is *within this batch*
      // only (index 0 fires immediately), so an ordinary single human move
      // is never delayed.
      let revealIndex = 0;
      labels.forEach((label, i) => {
        const actorId = actors[i];
        if (!actorId || actorId === data.perspective) return;
        const delay = revealIndex * botSpeedMs;
        revealIndex += 1;
        const text = `${playerName(actorId)} ${describeMoveLabel(label)}`;
        if (delay <= 0) {
          pushMoveFeed(text);
        } else {
          setTimeout(() => {
            if (stopped) return;
            pushMoveFeed(text);
          }, delay);
        }
      });
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
      const action = findTargetableAction(ct.instanceId, ct.send.type, ct.send.ability_index, ct.send.face, ct.send.mode);
      if (action) {
        const expanded = expandMultiTargetRequirements(action.targets || []);
        const sameShape = ct.isTapChoice || ct.isSacrificeChoice
          ? Array.isArray(ct.requirements)
          : expanded.requirements.length === (ct.requirements || []).length;
        if (sameShape && Number.isInteger(ct.reqIndex)) castTargeting = ct;
      }
    }
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
      const res = transport.rewind
        ? await transport.rewind(1)
        : await rewindGame(sessionId, 1);
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
    const stackNonEmpty = s.stack.length > 0;
    if (!stackNonEmpty) stackAside = false;

    root.innerHTML = `
      <div class="goldfish${pending || castTargeting ? ' choosing' : ''}">
        ${moveFeedHtml()}
        <div class="gf-topbar">
          <div class="gf-turninfo">
            <span class="gf-turn" title="Regel 500.1 zählt jeden Spielerzug einzeln – das ist Spielzug ${s.turn_number}.">Zug ${s.round_number || s.turn_number}</span>
            <span class="gf-step">${escapeHtml(labelPhase(s.current_phase))} · ${escapeHtml(labelStep(s.current_step))}</span>
            ${turnOrderHtml(live, s)}
            ${s.day_night ? `<span class="gf-daynight gf-daynight-${s.day_night}">${s.day_night === 'night' ? '🌙 Nacht' : '☀️ Tag'}</span>` : ''}
          </div>
        </div>

        ${dummy ? opponentStripHtml(dummy) : ''}

        ${planechaseHtml(s, actions)}

        ${gameOver ? gameOverHtml(s, seatId ? s.players.find((p) => p.id === seatId) : live[0]) : ''}
        ${statusHtml()}
        ${view.observer ? '<p class="server-status gf-observer-note">👁️ Beobachter-Modus – du siehst das öffentliche Spielfeld, aber keine Handkarten.</p>' : ''}
        ${waitingOnChoiceHtml(s)}
        ${pending ? pendingChoiceHtml(pending) : ''}
        ${castTargeting ? castTargetModalHtml() : ''}

        ${controlsHtml(stackNonEmpty, pending, gameOver)}

        ${blockerPanelHtml(actions, s)}

        ${boardsHtml(live, s, byInstance, pending, seatId)}

        ${stackNonEmpty && !pending ? stackOverlayHtml(s, stackAside) : ''}

        ${delayedTriggersPanelHtml(view)}

        ${moveLogHtml(view.move_log)}
      </div>
    `;
    wire();
    syncAutoPass();
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
      ? `<button type="button" class="primary" data-action='${escapeAttr(JSON.stringify({ type: 'roll_planar_die' }))}' title="Planarwürfel werfen (Regel 901.6): 1× Chaos, 1× Planarwanderung, 4× leer. Kostet {X} = bisherige Würfe in diesem Zug.">🎲 Planarwürfel (${escapeHtml(roll.cost_label || '{0}')})</button>`
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
          <span class="gf-planechase-count" title="Verbleibende Karten im Planarstapel">${s.planar_deck_count || 0} im Stapel</span>
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

  /**
   * The turn-order strip in the topbar: every seat, in the same sequence as
   * the boards below it, with the active player marked.
   *
   * Deliberately the *board* order rather than "active player first": the
   * strip is a legend for the layout, so the two have to read as one
   * statement, and a strip that re-sorts itself every turn is harder to
   * follow than a fixed seating chart. Replaces the older "Aktiv: X" badge,
   * which said strictly less (it named the active player; this names them
   * *and* who is up after them).
   */
  function turnOrderHtml(order, s) {
    if (order.length < 2) return '';
    const arrow = '<span class="gf-turnorder-arrow" aria-hidden="true">→</span>';
    const seats = order.map((p) => {
      const isActive = p.id === s.active_player_id;
      const classes = ['gf-turnorder-seat'];
      if (isActive) classes.push('gf-turnorder-active');
      if (p.id === view.perspective) classes.push('gf-turnorder-me');
      // A player who has left is skipped by `next_active_index`, so they're
      // shown struck through rather than dropped: the seating didn't change,
      // the turn just passes over them now.
      if (p.has_lost) classes.push('gf-turnorder-out');
      const title = [
        isActive ? 'am Zug' : '',
        p.id === view.perspective ? 'du' : '',
        p.has_lost ? 'ausgeschieden – wird übersprungen' : '',
      ].filter(Boolean).join(', ');
      // The same banner colour as that player's board below, so the strip
      // is a legend for the *colours* too and not only for the order.
      const banner = seatStatus(p.id)?.banner_color;
      const dot = banner
        ? `<span class="gf-turnorder-dot" style="background: ${escapeAttr(bannerGradients(banner).strip)}" aria-hidden="true"></span>`
        : '';
      return `<span class="${classes.join(' ')}"${title ? ` title="${escapeAttr(title)}"` : ''}>${isActive ? '▶ ' : ''}${dot}${escapeHtml(p.name)}</span>`;
    });
    return `
      <span class="gf-turnorder" title="Zugreihenfolge (Regel 500.1) – dieselbe Reihenfolge wie die Spielfelder darunter. ↻: danach geht es wieder von vorn los.">
        ${seats.join(arrow)}<span class="gf-turnorder-arrow" aria-hidden="true">↻</span>
      </span>`;
  }

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
      ? `<button id="gf-zones-side" type="button" title="Zonen-Spalten (Bibliothek, Friedhof …) nach ${zonesInside ? 'außen an die Ränder' : 'innen zur Mitte'} legen">⇄ Zonen: ${zonesInside ? 'innen' : 'außen'}</button>`
      : '<button id="gf-zones-side" type="button" title="Zonen-Spalte (Bibliothek, Friedhof …) auf die andere Seite legen">⇄ Zonen-Seite</button>';
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
        <div class="gf-controls">
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
    const myTurn = !view.perspective || view.state.active_player_id === view.perspective;
    return `
      <div class="gf-controls">
        <button id="gf-advance" type="button" class="primary" ${busy || gameOver || pending || !myTurn ? 'disabled' : ''}>Nächster Schritt →</button>
        ${allowFastForward ? `<button id="gf-next-decision" type="button" title="Überspringt Schritte ohne Entscheidung und hält bei der nächsten Wahl des aktiven Spielers" ${busy || gameOver || pending || !myTurn ? 'disabled' : ''}>⏭ Nächste Entscheidung</button>` : ''}
        ${stackNonEmpty && !pending ? `<button type="button" data-action='${escapeAttr(JSON.stringify({ type: 'pass_priority' }))}'>Priorität abgeben (Stack auflösen)</button>` : ''}
        ${allowRewind ? `<button id="gf-rewind" type="button" ${busy || !view.can_rewind ? 'disabled' : ''}>↶ Zurücknehmen</button>` : ''}
        ${zonesSideButtonHtml()}
        ${extra}
      </div>`;
  }

  /** Whether this session plays priority out for real (RULE 117). */
  function interactivePriority() {
    return !!view?.priority?.interactive && !view.observer;
  }

  /** Whether this client is the one the game is currently waiting on. */
  function hasPriority() {
    return !!view?.perspective && view.priority?.player_id === view.perspective;
  }

  // The shared-game toolbar. "Passen" is the only way forward: a step ends
  // when every player passes in succession on an empty stack (RULE 117.4),
  // so there is deliberately no "advance the turn" button to press.
  function priorityControlsHtml(pending, gameOver, extra) {
    const mine = hasPriority();
    const disabled = busy || gameOver || pending || !mine;
    return `
      <div class="gf-controls gf-priority-controls">
        ${passButtonHtml(disabled)}
        ${skipToActionButtonHtml(disabled)}
        ${gameOver ? '' : priorityBadgeHtml()}
        ${zonesSideButtonHtml()}
        ${extra}
        ${gameOver ? '' : autoPassControlHtml()}
      </div>`;
  }

  // Both the toolbar and each player's own banner (`playerBoardHtml`) carry
  // a pass button — on a two-board screen the toolbar can be a long way
  // from the cards you're looking at. They're the same control, so it's a
  // data attribute rather than an id, and `wire()` binds all of them.
  function passButtonHtml(disabled, extraClass = '') {
    const label = view.state.stack.length > 0 ? 'Passen (Stack auflösen)' : 'Passen →';
    return `<button type="button" class="primary${extraClass}" data-pass-priority ${disabled ? 'disabled' : ''}>${label}</button>`;
  }

  // The goldfish board's "⏭ Nächste Entscheidung" has no shared-game
  // equivalent (skipping *steps* would skip the opponent's response
  // windows), so this is the legal version of the same idea: keep passing
  // while the only thing on offer is passing, and stop at the first window
  // that actually asks something of you.
  //
  // Like `passButtonHtml`, this is drawn both in the toolbar and on this
  // client's own board banner, so it's a data attribute rather than an id —
  // two elements sharing one id would leave the second one dead.
  function skipToActionButtonHtml(disabled, extraClass = '') {
    return `<button type="button" class="gf-skip-empty${extraClass}" data-skip-empty title="Passt Prioritätsfenster ohne jede Handlungsmöglichkeit sofort durch und hält bei der nächsten echten Entscheidung" ${disabled ? 'disabled' : ''}>⏭ Nächste Aktion</button>`;
  }

  function priorityBadgeHtml(compact = false) {
    if (!interactivePriority()) return '';
    const holder = view.priority?.player_id;
    if (hasPriority()) {
      return `<span class="gf-priority-badge gf-priority-mine">${compact ? '⚡ Priorität' : 'Du bist dran (Priorität)'}${autoPassCountdownHtml()}</span>`;
    }
    return `<span class="gf-priority-badge">⏳ ${escapeHtml(playerName(holder))} ist dran …</span>`;
  }

  // The live countdown on the "you're up" badge. Purely cosmetic — the
  // actual pass is fired by the timer in `restartAutoPass`.
  function autoPassCountdownHtml() {
    if (!autoPassArmed()) return '';
    return ` · <span class="gf-autopass-count" data-autopass-count>${autoPassSeconds}</span>s`;
  }

  // Auto-pass is a per-player convenience, so it's adjustable right here
  // rather than only in Einstellungen — you change your mind about it
  // mid-game, usually the moment it passes on something you wanted.
  function autoPassControlHtml() {
    const on = getAutoPassEnabled();
    return `
      <label class="gf-autopass" title="Nach Ablauf der Zeit wird automatisch gepasst. Jede Aktion auf dem Brett stoppt den Countdown.">
        <input type="checkbox" id="gf-autopass-toggle" ${on ? 'checked' : ''} />
        Auto-Pass
        <input type="number" id="gf-autopass-seconds" min="${MIN_AUTO_PASS_SECONDS}" max="${MAX_AUTO_PASS_SECONDS}"
               value="${autoPassSeconds}" ${on ? '' : 'disabled'} /> s
      </label>
      <label class="gf-autopass" title="Wie der ⏭-Knopf, aber dauerhaft ein: Sobald dir wirklich nichts anderes als 'Passen' offensteht (z. B. während des gegnerischen Zugs, wenn du kein Instant in der Hand hast), passt der Client sofort für dich – ohne Countdown, weil es nichts zu entscheiden gibt. Sobald irgendeine echte Aktion angeboten wird (eine Karte spielen/zaubern, angreifen, blocken …), greift das nicht mehr und du bist wieder am Zug.">
        <input type="checkbox" id="gf-skip-empty-toggle" ${getAutoSkipEmpty() ? 'checked' : ''} />
        Leere Fenster automatisch überspringen
      </label>
      ${botSpeedControlHtml()}`;
  }

  // VIS-7: a bot's whole turn arrives as one pushed view (`run_bots` answers
  // it to completion before the single broadcast), so without this its
  // moves would all show up in the feed at once. Lets a player watching a
  // bot opponent choose how spread out the "Bot hat X gespielt" reveals
  // should be — 0 keeps the old instant behaviour.
  const BOT_SPEED_LABELS = { 0: 'Sofort', 900: 'Normal', 2000: 'Langsam' };

  function botSpeedControlHtml() {
    const options = BOT_SPEED_MS_OPTIONS.map(
      (ms) => `<option value="${ms}" ${ms === botSpeedMs ? 'selected' : ''}>${BOT_SPEED_LABELS[ms] || `${ms} ms`}</option>`
    ).join('');
    return `
      <label class="gf-autopass" title="Wie schnell die Aktionen eines Bots nacheinander im Verlauf/Feed auftauchen, statt alle auf einmal (der ganze Bot-Zug kommt als eine Antwort vom Server).">
        Bot-Tempo
        <select id="gf-bot-speed">${options}</select>
      </label>`;
  }

  // Someone else is answering a choice this client may not see (its options
  // can name cards in a hidden zone, so the server strips them and sends
  // this marker instead — `services/game_session.py`'s `_redact_hidden_zones`).
  function waitingOnChoiceHtml(s) {
    const waiting = s.waiting_on_choice;
    if (!waiting) return '';
    const who = playerName(waiting.player_id);
    const what = waiting.prompt ? ` (${escapeHtml(waiting.prompt)})` : '';
    return `<p class="server-status pending gf-waiting-choice">⏳ ${escapeHtml(who)} trifft gerade eine Entscheidung${what} …</p>`;
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
          `<option value="">— blockt nicht —</option>`,
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
        <h4>🛡️ Blocker deklarieren</h4>
        <p class="hint">
          ${escapeHtml(playerName(s.active_player_id))} greift an. Weise deine
          Kreaturen zu und bestätige – der ganze Block wird auf einmal
          deklariert (nötig für Bedrohlich &amp; Co., Regel 702.111b). "Blockt
          nicht" ist eine gültige Entscheidung: bestätige einfach ohne
          Zuweisung, um komplett auf den Block zu verzichten.
        </p>
        ${rows}
        <div class="gf-controls">
          <button id="gf-submit-blocks" type="button" class="primary" ${busy ? 'disabled' : ''}>
            ${count ? `Block bestätigen (${count})` : 'Keine Blocker bestätigen'}
          </button>
          <button id="gf-clear-blocks" type="button" ${busy || !count ? 'disabled' : ''}>Zurücksetzen</button>
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
      isMe ? '<span class="gf-seat-badge gf-seat-you">Du</span>' : '',
      isActive ? '<span class="gf-seat-badge gf-seat-active">am Zug</span>' : '',
      p.has_lost
        ? `<span class="gf-seat-badge gf-seat-out">${p.loss_reason === 'conceded' ? 'aufgegeben' : 'ausgeschieden'}</span>`
        : '',
      // Not a rules state at all — this player's browser is gone. The
      // server passes priority for them meanwhile, so the game keeps
      // moving; the badge is why it looks like they're doing nothing.
      seat?.connected === false
        ? '<span class="gf-seat-badge gf-seat-away" title="Verbindung verloren – der Platz bleibt kurz reserviert">⚡ getrennt</span>'
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
    const priorityBits = !interactivePriority() || s.game_over
      ? ''
      : isMe
        ? `${priorityBadgeHtml(true)}${passButtonHtml(priorityDisabled, ' gf-banner-pass')}${skipToActionButtonHtml(priorityDisabled, ' gf-banner-skip')}`
        : holdsPriority
          ? '<span class="gf-priority-badge">⏳ ist dran …</span>'
          : '';
    // Folding an opponent away is only offered at a pod-sized table — with
    // one opponent there is nothing to scroll past.
    const opponents = s.players.filter((o) => !o.is_dummy && o.id !== seatId).length;
    const foldable = seatId != null && !isMe && opponents > 1;
    const folded = foldable && collapsedBoards.has(p.id);
    return `
      <section class="gf-player-board${isMe ? ' gf-own-board' : ''}${seatId && !isMe ? ' gf-opponent-board' : ''}${p.has_lost ? ' gf-board-out' : ''}${folded ? ' gf-board-folded' : ''}">
        <header class="gf-player-board-head${bannerCss ? ' gf-banner-tinted' : ''}"${bannerAttrs}>
          ${
            foldable
              ? `<button type="button" class="gf-board-fold" data-fold-board="${escapeAttr(p.id)}" title="${folded ? 'Spielfeld ausklappen' : 'Spielfeld einklappen'}" aria-expanded="${folded ? 'false' : 'true'}">${folded ? '▸' : '▾'}</button>`
              : ''
          }
          <h3>${escapeHtml(p.name)}${badges}</h3>
          ${priorityBits ? `<div class="gf-banner-priority">${priorityBits}</div>` : ''}
          <div class="gf-banner-stats">
            ${manaPoolHtml(p.mana_pool)}
            ${manaPotentialHtml(view.mana_potential?.[p.id])}
            ${lifeBox('Leben', p.life)}
            ${playerCountersHtml(p, s)}
          </div>
        </header>
        ${folded ? foldedBoardHtml(p, bf) : ''}
        <div class="gf-play gf-zones-${zonesSideFor(index, total)}"${folded ? ' hidden' : ''}>
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
              <h4>Hand (${p.hand_count != null ? p.hand_count : p.hand.length})${ownHand ? '' : opponentHandToggleHtml()}</h4>
              ${handHtml(p, byInstance, pending, ownHand)}
            </div>
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
      `${bf.length} Permanent${bf.length === 1 ? '' : 'e'}`,
      `${creatures} Kreatur${creatures === 1 ? '' : 'en'}`,
      `Hand ${p.hand_count != null ? p.hand_count : p.hand.length}`,
      `Bibliothek ${p.library_count}`,
      `Friedhof ${p.graveyard.length}`,
      `Exil ${p.exile.length}`,
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
        return `<p class="empty-state gf-hand-hidden">${count} verdeckte Karte${count === 1 ? '' : 'n'}</p>`;
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
      <label class="gf-bf-toggle gf-hand-toggle" title="Zeigt die Anzahl als verdeckte Karten statt nur als Zahl. Die Karten selbst sieht niemand – Regel 400.2.">
        <input type="checkbox" class="gf-opp-hand-toggle" ${getShowOpponentHand() ? 'checked' : ''} />
        verdeckte Karten zeigen
      </label>`;
  }

  // One face-down card: the player's own chosen sleeve if they uploaded one
  // (Einstellungen tab, `setAssets`), otherwise a plain patterned back.
  function faceDownCardHtml() {
    if (assetsSleeveImageUrl) {
      return `<div class="card has-image gf-face-down"><img src="${escapeAttr(assetsSleeveImageUrl)}" alt="Verdeckte Karte" /></div>`;
    }
    return '<div class="card gf-face-down" title="Verdeckte Karte"></div>';
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
  // except `replacement_order` (RULE 616.1) and `order_triggers`
  // (RULE 603.3b), which get a drag-and-drop reorderable list instead (see
  // `replacementOrderHtml`/`triggerOrderHtml`).
  function pendingChoiceHtml(pending) {
    const icon = CHOICE_ICONS[pending.kind] || '❔';
    const heading = pending.prompt || pending.description || 'Entscheidung nötig';
    const body = pending.kind === 'replacement_order'
      ? replacementOrderHtml(pending)
      : pending.kind === 'order_triggers'
        ? triggerOrderHtml(pending)
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
        const action = {
          type: 'choose', option_id: opt.id, instance_id: opt.instance_id, name: opt.label,
        };
        const res = transport.sendAction
          ? await transport.sendAction(action)
          : await sendGameAction(sessionId, action);
        if (!res.ok) {
          setStatus(`Aktion nicht erlaubt: ${res.data?.detail ?? res.status}`, 'warning');
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
      <p class="gf-reorder-hint">Per Drag &amp; Drop in die gewünschte Reihenfolge bringen — die oberste Fähigkeit kommt zuerst auf den Stack und wird daher zuletzt aufgelöst.</p>
      <ul class="gf-reorder-list gf-trigger-order-list">${items}</ul>
      <div class="gf-modal-foot">
        <button type="button" class="primary" data-trigger-order-confirm>Bestätigen</button>
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
          setStatus(`Aktion nicht erlaubt: ${res.data?.detail ?? res.status}`, 'warning');
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
    root.querySelector('#gf-advance')?.addEventListener('click', () => act({ type: 'advance_step' }));
    root.querySelector('#gf-next-decision')?.addEventListener('click', () => act({ type: 'advance_to_decision' }));
    root.querySelector('#gf-rewind')?.addEventListener('click', rewind);
    // Every pass button on the page (toolbar + each own-board banner).
    root.querySelectorAll('[data-pass-priority]').forEach((el) => {
      el.addEventListener('click', () => act({ type: 'pass_priority' }));
    });
    // Every "⏭ Nächste Aktion" on the page (toolbar + own-board banner).
    root.querySelectorAll('[data-skip-empty]').forEach((el) => {
      el.addEventListener('click', () => {
        skipBurstArmed = true;
        autoPassCancelled = false;
        syncAutoPass();
      });
    });
    root.querySelector('#gf-skip-empty-toggle')?.addEventListener('change', (e) => {
      saveSettings({ autoSkipEmpty: e.target.checked });
      render();
    });
    root.querySelector('#gf-bot-speed')?.addEventListener('change', (e) => {
      const saved = saveSettings({ botSpeedMs: e.target.value });
      botSpeedMs = saved.botSpeedMs;
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
    // Show/hide an opponent's face-down hand (their cards are never on the
    // wire either way — RULE 400.2).
    root.querySelectorAll('.gf-opp-hand-toggle').forEach((el) => {
      el.addEventListener('change', (e) => {
        saveSettings({ showOpponentHand: e.target.checked });
        render();
      });
    });

    // Auto-pass, adjustable mid-game (it's a per-player convenience, and
    // people change their mind about it the moment it costs them a
    // response). Both controls persist to the same cookies Einstellungen
    // writes, so the change sticks for the next game too.
    root.querySelector('#gf-autopass-toggle')?.addEventListener('change', (e) => {
      saveSettings({ autoPass: e.target.checked });
      autoPassCancelled = false;
      stopAutoPass();
      render();
    });
    root.querySelector('#gf-autopass-seconds')?.addEventListener('change', (e) => {
      const saved = saveSettings({ autoPassSeconds: e.target.value });
      autoPassSeconds = saved.autoPassSeconds;
      stopAutoPass();
      render();
    });
    // Touching the board at all means "I'm still thinking" — the countdown
    // for this window stops rather than passing out from under the player.
    if (interactivePriority()) {
      root.querySelector('.goldfish')?.addEventListener('pointerdown', (e) => {
        // …except the auto-pass/skip controls themselves, which would
        // otherwise disable the very thing you just switched on.
        if (e.target.closest('.gf-autopass') || e.target.closest('[data-skip-empty]')) return;
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
        const { iid, face, mode, entwine } = JSON.parse(el.dataset.castX);
        const input = root.querySelector(`[data-x-input="${xKey(iid, face)}"]`);
        const x = Math.max(0, Math.floor(Number(input?.value) || 0));
        const kicked = readKicker(iid, face);
        const kicker_x = readKickerX(iid, face);
        act({ type: 'cast_spell', instance_id: iid, x, face, kicked, kicker_x, mode, entwine });
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
        const action = findTargetableAction(iid, info.type, info.ability_index, info.face, info.mode);
        if (!action) return;
        const input = root.querySelector(`[data-x-input="${xKey(iid, info.face)}"]`);
        const x = action.has_x ? Math.max(0, Math.floor(Number(input?.value) || 0)) : 0;
        const kicked = action.has_kicker ? readKicker(iid, info.face) : 0;
        const kicker_x = action.kicker_has_x ? readKickerX(iid, info.face) : 0;
        const send = info.type === 'activate_ability'
          ? { type: 'activate_ability', instance_id: iid, ability_index: info.ability_index, name: action.name }
          : {
            type: 'cast_spell', instance_id: iid, name: action.name, face: info.face, kicked, kicker_x,
            mode: info.mode, entwine: info.entwine,
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
        const requirements = [{ label: 'zu opferndes Permanent', options, optional: false }];
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
  function findTargetableAction(iid, type, abilityIndex, face, mode) {
    const modeKey = JSON.stringify(mode ?? null);
    return (view?.legal_actions || []).find(
      (a) =>
        a.type === type &&
        a.instance_id === iid &&
        (type !== 'activate_ability' || a.ability_index === abilityIndex) &&
        (a.face || undefined) === (face || undefined) &&
        JSON.stringify(a.mode ?? null) === modeKey,
    );
  }

  function finishCastIfReady() {
    if (!castTargeting) return;
    if (castTargeting.reqIndex >= castTargeting.requirements.length) {
      const { send, targets, groups, x, isTapChoice, isSacrificeChoice } = castTargeting;
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
    const cached = imageCache?.get((o.name || '').toLowerCase());
    if (cached) {
      if (showBack && cached.backSmall) return cached.backSmall;
      if (!showBack && cached.small) return cached.small;
    }
    const isToken = o.is_token || (o.card_id || '').startsWith('token:');
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
    if (imageUrl) classes.push('has-image');
    if (o.tapped) classes.push('tapped');
    if (o.summoning_sick) classes.push('summoning-sick');
    if (o.attacking) classes.push('attacking');
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
    // RULE 714: a Saga's chapter progress, mirroring the loyalty badge above
    // (and, like it, pulled out of the generic counter badge below so "lore"
    // doesn't show twice). `saga_final_chapter` is only set once the oracle
    // parser recognized at least one chapter line; without it, just the raw
    // lore count is shown (no "/N" to compare against).
    const lore = (o.counters || {}).lore;
    const sagaBadge = o.is_saga && lore != null
      ? `<span class="gf-loyalty-badge gf-saga-badge" title="Sagen-Kapitel (Regel 714)">📜 ${lore}${o.saga_final_chapter ? `/${o.saga_final_chapter}` : ''}</span>`
      : '';
    // RULE 310.4c: a battle's current defense is its defense-counter count,
    // badged like loyalty/lore above (and likewise pulled out of the generic
    // counter badge so "defense" doesn't show twice). RULE 310.8: the
    // protector is the player who defends it — shown by name, resolved
    // against the view's own player list, since a raw id means nothing here.
    const protectorName = o.protector_id ? playerName(o.protector_id) : null;
    const battleBadge = o.is_battle && o.defense != null
      ? `<span class="gf-loyalty-badge gf-battle-badge" title="Verteidigung (Regel 310.4c)${protectorName ? ` — beschützt von ${escapeAttr(protectorName)}` : ''}">🛡 ${o.defense}${protectorName ? ` · ${escapeHtml(protectorName)}` : ''}</span>`
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
    // RULE 708.2: a face-down permanent shows *what put it there* (morph,
    // disguise, manifest, cloak) and nothing about the card underneath —
    // which is all the payload carries anyway. The kind matters to the
    // player because it decides how it can be turned face up (RULE
    // 702.37e/701.40b) and whether it has ward {2} (RULE 702.168a/701.58a).
    const faceDownLabels = {
      morph: 'Morph', disguise: 'Verkleidung', manifest: 'Manifestiert', cloak: 'Verhüllt',
    };
    const faceDownBadge = o.face_down
      ? `<span class="gf-facedown-badge" title="Verdeckte bleibende Karte (Regel 708.2): 2/2 ohne Namen und Text">🎭 ${escapeHtml(faceDownLabels[o.face_down_kind] || 'Verdeckt')}</span>`
      : '';
    const effectsSummary = effectSummaryHtml(o);
    // A double-faced permanent (transform/modal DFC) gets a "🔄 peek other
    // face" button — purely a client-side preview (`flippedForView`), not
    // an actual transform (RULE 712.8 stays a real game action, offered
    // instead among `buttons` when the card's own ability allows it).
    const flipButton = o.has_back_face
      ? `<button type="button" class="gf-card-flip" data-flip-toggle="${o.instance_id}" title="Andere Seite ansehen" aria-label="Andere Seite ansehen">🔄</button>`
      : '';
    return `
      <div class="gf-card-slot">
        <div class="${classes.join(' ')}" data-hover-card="${escapeHtml(o.name)}" title="${escapeHtml(o.name)}${pt}${o.tapped ? ' — getappt' : ''}">${inner}${flipButton}${attackBadge}${loyaltyBadge}${sagaBadge}${battleBadge}${counterBadge}${keywordBadge}${adventureBadge}${preparedBadge}${preparedCopyBadge}${faceDownBadge}${effectsSummary}</div>
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

  // RULE 700.2: a modal spell offers one `cast_spell` action per mode (or
  // per legal mode combination — `_modal_cast_actions`), each tagged with
  // `mode`/`mode_description`. Without this, every offered variant renders
  // as an identical "✨ Zaubern" button and `findTargetableAction` picks
  // whichever happens to come first in `legal_actions` — the player never
  // actually chooses a mode. `a.entwine` (RULE 702.42a) reuses the same
  // "both modes" `mode: "both"` shape, just priced, so it gets its own
  // label rather than falling back to the plain mode text.
  function modeHint(a) {
    if (!a.mode_description) return a.entwine ? ' (Verflechten)' : '';
    const suffix = a.entwine ? ' (Verflechten)' : '';
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
    const title = a.kicker_cost ? `Kicker ${a.kicker_cost}` : 'Kicker';
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
            <button type="button" class="gf-card-action" data-cast-x='${escapeAttr(JSON.stringify({ iid: a.instance_id, face: a.face, mode: a.mode, entwine: a.entwine }))}'>✨ Zaubern (${suffix})${modeHint(a)}${faceHint(a)}</button>
          </div>
        `);
      } else if (a.type === 'cast_spell') {
        const hint = a.base_cost && a.effective_cost && a.base_cost !== a.effective_cost
          ? ` 💰${escapeHtml(a.effective_cost)}`
          : '';
        buttons.push(
          actionButton(
            { type: 'cast_spell', instance_id: a.instance_id, name: a.name, face: a.face, mode: a.mode, entwine: a.entwine },
            `✨ Zaubern${modeHint(a)}${hint}${faceHint(a)}`
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
  // hand-zone `activate_hand_mana` one).
  function colorSplitHtml(a, kind) {
    const colors = ['W', 'U', 'B', 'R', 'G'];
    const inputs = colors
      .map(
        (c) =>
          `<label class="gf-split-color" title="${c}">${MANA_SYMBOL_EMOJI[c]}<input type="number" min="0" max="${a.combination_total}" value="0" data-split-color="${c}" /></label>`
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
    const startInfo = JSON.stringify({
      iid, type: a.type, ability_index: a.ability_index, face: a.face,
      mode: a.mode, entwine: a.entwine,
    });
    const label = a.type === 'activate_ability'
      ? `⚡ ${escapeHtml(a.cost_label || 'Aktivieren')} → Ziel ▾`
      : `✨ Zaubern${modeHint(a)} → Ziel ▾${faceHint(a)}`;
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
        `<span class="gf-pcounter" title="Der Eine Ring verlockt dich – Stufe ${p.ring_level} von 4 (Regel 701.52)">💍 ${p.ring_level}/4</span>`,
      );
    }
    if (s.monarch_id === p.id) {
      bits.push('<span class="gf-pcounter gf-pcounter--designation" title="Monarch (Regel 725): zieht in seinem Endsegment eine Karte">👑 Monarch</span>');
    }
    if (s.initiative_id === p.id) {
      bits.push('<span class="gf-pcounter gf-pcounter--designation" title="Initiative (Regel 726)">⚔️ Initiative</span>');
    }
    if (p.has_city_blessing) {
      // RULE 702.131c: no shared holder, unlike Monarch/Initiative above —
      // every player who has ascended shows this, any number at once.
      bits.push('<span class="gf-pcounter gf-pcounter--designation" title="Segen der Stadt (Regel 702.131): dauerhaft, sobald du 10+ Permanente kontrolliert hast">🏙️ Segen der Stadt</span>');
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
        `<span class="gf-pcounter" title="${escapeAttr(`Abgeschlossene Dungeons (Regel 309.7): ${p.completed_dungeons.join(', ')}`)}">🏁 ${p.completed_dungeons.length}</span>`,
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
    energy: 'Energie-Marken (Regel 122)',
    experience: 'Erfahrungsmarken',
    rad: 'Strahlungsmarken',
  };
  function counterIcon(kind) {
    return PLAYER_COUNTER_ICONS[kind] || '🔘';
  }
  function counterLabel(kind) {
    return PLAYER_COUNTER_LABELS[kind] || `${kind}-Marken`;
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
    const parts = order.filter((c) => pool[c] > 0).map((c) => `<span class="gf-mana">${MANA_SYMBOL_EMOJI[c]}${pool[c]}</span>`);
    const restrictedParts = restrictedManaHtml(pool.restricted, MANA_SYMBOL_EMOJI, order);
    const empty = !parts.length && !restrictedParts.length;
    return `<div class="gf-manapool" title="Mana-Pool">${empty ? '<span class="empty-state">kein Mana</span>' : parts.join('') + restrictedParts.join('')}</div>`;
  }

  // "Mana-Potenzial": how much more mana this player could still produce
  // this turn from untapped/unexiled sources ("offen", a live non-mutating
  // simulation — `game/mana_potential.py`'s `open_potential_summary`), next
  // to how much they've already actually produced this turn ("genutzt",
  // `used_potential_summary`) — the two sum to this turn's total accessed
  // mana capacity. ``potential`` is `view.mana_potential[player_id]`
  // (absent for a seat this view doesn't own — RULE 400.2, same as the
  // hand array itself).
  function manaPotentialHtml(potential) {
    if (!potential) return '';
    const order = ['W', 'U', 'B', 'R', 'G', 'C'];
    const row = (amounts, label, cls) => {
      const parts = order
        .filter((c) => amounts[c] > 0)
        .map((c) => `<span class="gf-mana">${MANA_SYMBOL_EMOJI[c]}${amounts[c]}</span>`);
      if (!parts.length) return '';
      return `<span class="gf-mana-potential-row ${cls}"><span class="gf-mana-potential-label">${label}</span>${parts.join('')}</span>`;
    };
    const openRow = row(potential.open || {}, 'Offen', 'gf-mana-potential-open');
    const usedRow = row(potential.used || {}, 'Genutzt', 'gf-mana-potential-used');
    if (!openRow && !usedRow) return '';
    return `<div class="gf-mana-potential" title="Mana-Potenzial: noch verfügbar (offen) + diesen Zug bereits erzeugt (genutzt)">${openRow}${usedRow}</div>`;
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

  // VIS-5: the transient "Bob hat X gespielt" toasts `pushMoveFeed` queues.
  function moveFeedHtml() {
    if (!moveFeed.length) return '';
    return `<div class="gf-move-feed" aria-live="polite">${moveFeed
      .map((entry) => `<div class="gf-move-feed-item">${escapeHtml(entry.text)}</div>`)
      .join('')}</div>`;
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
      : '<p class="empty-state">Keine aktiven statischen Fähigkeiten.</p>';

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
    view = null;
    moveFeed = [];
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
