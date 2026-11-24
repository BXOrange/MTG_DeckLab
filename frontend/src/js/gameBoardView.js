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
import { getBoardLayout } from './boardLayout.js';
import { getGameAudio, gameAudioEvents } from './gameAudio.js';
import { sendGameAction, rewindGame, saveUiDraft } from './api.js';
import { getCookie, setCookie } from './cookies.js';
import { getBoardScale, onBoardScaleChange } from './boardScale.js';
import { bannerColorLabel, bannerStyle } from './bannerColors.js';
import { MANA_SYMBOL_EMOJI, renderOracleText } from './cardTile.js';
import { getBotSpeedMs, getCompactView, saveSettings } from './settings.js';
import { t } from './i18n.js';
import { setHeaderMessage } from './headerMessage.js';

import { boardOrder, createBoardLayout, planechaseHtml as renderPlanechase } from './gameBoard/boardLayout.js';
import { wireBoardGeometry as installBoardGeometry } from './gameBoard/boardGeometry.js';
import { createBoardChat } from './gameBoard/boardChat.js';
import { createPriorityController } from './gameBoard/priorityController.js';
import { createPlayerBoardRenderer } from './gameBoard/playerBoards.js';
import { escapeHtml, escapeAttr } from './gameBoard/html.js';
import { STEP_LABELS, labelPhase, labelStep, SELECTION_KINDS } from './gameBoard/labels.js';
import { expandMultiTargetRequirements, defenderPayload, xKey, kickerKey } from './gameBoard/castForm.js';
import { stackItemSig, ghostItemName, syntheticStackItemFromMoveLabel } from './gameBoard/stackView.js';
import { zoneListHtml, restrictedManaHtml, positionEffectPopover, measurementValue, triggerOptionKey } from './gameBoard/miscHtml.js';
import { castTargetHtml, manaPotentialHtml } from './gameBoard/cardForms.js';
import { staticEffectsPanelHtml, playerCountersHtml, commanderDamageHtml } from './gameBoard/playerPanels.js';
import { createCastController } from './gameBoard/castController.js';
import { createCardRenderer } from './gameBoard/cardRenderer.js';
import { createDragController } from './gameBoard/dragController.js';
import { createChoiceRenderer } from './gameBoard/choices.js';

const CHAT_BOTTOM_THRESHOLD_PX = 24; // Keep reading position unless near the newest message.

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
 * @param {{sendAction?: Function, rewind?: Function, saveUiDraft?: Function}} [opts.transport] How
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

  const audio = getGameAudio();
  let audioView = null;
  let audioSession = null;
  let root = null;
  let sessionId = null;
  let view = null;
  let latestByInstance = {};
  let dragSource = null;
  // Local presentation order per drag-reorderable zone (hand, battlefield rows);
  // never changes game zones. Keyed by `data-order-zone`.
  const zoneOrder = new Map();

  let dragHandlersInstalled = false;
  let busy = false;
  let status = '';
  let statusKind = '';
  let measurementDraft = { key: null, text: '' };
  // PAR-203: the text typed into a free-text choice (a card name or creature type), kept across repaints.
  let choiceTextDraft = { key: null, text: '' };

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
  // Static-effect inspection is a session-local modal, shared by all boards.
  let showStatics = false;
  let staticsAside = false;
  // Four persisted layouts combine full-width/compact banners with mirrored
  // inner/outer zones. Stacked boards map the same zone choice to left/right.
  let { zonesInside, moreBattlefield } = getBoardLayout();
  window.addEventListener('board-layout-changed', () => {
    ({ zonesInside, moreBattlefield } = getBoardLayout());
    render();
  });
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
  let proliferateDraft = { key: null, ids: new Set() };
  let waitingChoiceAside = false;
  // VIS-14: the same push-aside for the RULE 115 target-picker modal
  // (`castTargetModalHtml`) — while true the board is live and the legal
  // targets are clickable right on it (`wirePickTargets`).
  let castTargetAside = false;
  // Attacking creatures whose "choose a defender" submenu is open (2+ legal
  // defenders, RULE 508.1a).
  const attackMenuOpen = new Set();
  let attackDraft = new Map();
  let attackDraftKey = null;

  // Live view of board state for the extracted renderers (see gameBoard/choices.js).
  const boardCtx = {
    get view() { return view; },
    get busy() { return busy; },
    get proliferateDraft() { return proliferateDraft; },
    set proliferateDraft(value) { proliferateDraft = value; },
    get measurementDraft() { return measurementDraft; },
    set measurementDraft(value) { measurementDraft = value; },
    get choiceTextDraft() { return choiceTextDraft; },
    set choiceTextDraft(value) { choiceTextDraft = value; },
    get replacementOrderDraft() { return replacementOrderDraft; },
    set replacementOrderDraft(value) { replacementOrderDraft = value; },
    get triggerOrderDraft() { return triggerOrderDraft; },
    set triggerOrderDraft(value) { triggerOrderDraft = value; },
    seatStatus,
    get dragHandlersInstalled() { return dragHandlersInstalled; },
    set dragHandlersInstalled(value) { dragHandlersInstalled = value; },
    get dragSource() { return dragSource; },
    set dragSource(value) { dragSource = value; },
    get latestByInstance() { return latestByInstance; },
    set latestByInstance(value) { latestByInstance = value; },
    confirmReplacementOrder, confirmTriggerOrder,
    prepareCastTargeting: (...args) => prepareCastTargeting(...args),
    get abilitySourceInstanceIds() { return abilitySourceInstanceIds; },
    set abilitySourceInstanceIds(value) { abilitySourceInstanceIds = value; },
    get assetsSleeveImageUrl() { return assetsSleeveImageUrl; },
    set assetsSleeveImageUrl(value) { assetsSleeveImageUrl = value; },
    get attackDraft() { return attackDraft; },
    set attackDraft(value) { attackDraft = value; },
    get attackMenuOpen() { return attackMenuOpen; },
    get cardMenuSerial() { return cardMenuSerial; },
    set cardMenuSerial(value) { cardMenuSerial = value; },
    get compactView() { return compactView; },
    set compactView(value) { compactView = value; },
    get expandedZones() { return expandedZones; },
    get flippedForView() { return flippedForView; },
    get mutualTargetPairIds() { return mutualTargetPairIds; },
    set mutualTargetPairIds(value) { mutualTargetPairIds = value; },
    get priority() { return priority; },
    get resolvedGhosts() { return resolvedGhosts; },
    set resolvedGhosts(value) { resolvedGhosts = value; },
    get targetedInstanceIds() { return targetedInstanceIds; },
    set targetedInstanceIds(value) { targetedInstanceIds = value; },
    get threeRows() { return threeRows; },
    set threeRows(value) { threeRows = value; },
    get tokenImages() { return tokenImages; },
    set tokenImages(value) { tokenImages = value; },
    get zoneOrder() { return zoneOrder; },
    updateTargetOverlays, withBusy,
    get root() { return root; },
    get castTargeting() { return castTargeting; },
    set castTargeting(value) { castTargeting = value; },
    get castTargetAside() { return castTargetAside; },
    set castTargetAside(value) { castTargetAside = value; },
    get choiceAside() { return choiceAside; },
    act, persistCastTargetingDraft, readKicker, readKickerAnnouncement, readKickerX, readReplicate, readX, render,
    requirementOwnerIndexForOption, selectedKickerAction, setStatus, submitManaActivation,
    wire: () => wire(),
    targetControllerChipHtml: (option) => targetControllerChipHtml(option),
    playerName: (id) => playerName(id),
  };
  const {
    playerName,
    targetControllerChipHtml,
    pendingChoiceHtml,
    replacementOrderHtml,
    triggerOrderHtml,
  } = createChoiceRenderer(boardCtx);
  const {
    finishCastIfReady,
    wireCostPayments,
    pickablesForBoard,
    findTargetableAction,
    wireCastForms,
    prepareCastTargeting,
    castTargetModalHtml,
    wirePickTargets,
  } = createCastController(boardCtx);
  const {
    wireCardActionsAndDrag,
  } = createDragController(boardCtx);
  const {
    battlefieldHtml,
    objGrid,
    handAreaHtml,
    resolveImageUrl,
    showsBackFace,
    stackItemHtml,
    railStackHtml,
    faceDownCardHtml,
    collapsibleZoneHtml,
    blindSideboardHtml,
  } = createCardRenderer(boardCtx);

  const priority = createPriorityController({
    getView: () => view,
    getRoot: () => root,
    getBusy: () => busy,
    getSessionId: () => sessionId,
    getAttackDraftSize: () => attackDraft.size,
    act,
    staticEffectsButtonHtml,
    t,
    escapeHtml,
    escapeAttr,
    stepLabels: STEP_LABELS,
  });
  const {
    actingSeat,
    cancelAutoPassForThisWindow,
    clearSkipAttempt,
    hasPriority,
    interactivePriority,
    paintCountdown,
    passButtonHtml,
    priorityBadgeHtml,
    priorityControlsHtml,
    railStopsHtml,
    railTimerHtml,
    resetSession: resetPrioritySession,
    syncAutoPass,
    updateTimerSeconds,
    wireStopsPanel,
    yieldBadgeHtml,
    yieldButtonsHtml,
  } = priority;
  const { podGrid, zonesSideFor } = createBoardLayout({
    getView: () => view,
    podGridMedia,
    getZonesInside: () => zonesInside,
  });
  const { boardsHtml } = createPlayerBoardRenderer({
    getView: () => view,
    getBusy: () => busy,
    seatStatus,
    transport,
    t,
    escapeHtml,
    escapeAttr,
    bannerStyle,
    bannerColorLabel,
    interactivePriority,
    yieldBadgeHtml,
    priorityBadgeHtml,
    manaPoolHtml,
    manaPotentialHtml,
    lifeBox,
    playerCountersHtml: (p, s) => playerCountersHtml(p, s, view),
    podGrid,
    zonesSideFor,
    getMoreBattlefield: () => moreBattlefield,
    objGrid,
    faceDownCardHtml,
    knownLibraryHtml,
    libraryTopHtml,
    collapsibleZoneHtml,
    zoneListHtml,
    blindSideboardHtml,
    getThreeRows: () => threeRows,
    battlefieldHtml,
    handAreaHtml,
  });
  const chat = createBoardChat({
    getView: () => view,
    getSessionId: () => sessionId,
    getTransport: () => transport,
    getRoot: () => root,
    applyView,
    render,
    resolveImageUrl,
    t,
    escapeHtml,
    escapeAttr,
    renderOracleText,
  });
  const {
    chatPanelHtml,
    resetSession: resetChatSession,
    revealPopupHtml,
    updateRevealPopup,
    wireEvents: wireChatEvents,
  } = chat;
  // Friedhof / Exil zone bodies the player has expanded. Both zones are
  // collapsed to just their header by default so a full graveyard (60+
  // entries) can't stretch the fixed-width side column and push the rest of
  // the board around — clicking the header toggles the list open, and the
  // open list is height-capped and scrolls inside itself. Keyed
  // `${playerId}:graveyard` / `${playerId}:exile`; purely a client-side
  // view state.
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
  function requirementOwnerIndexForOption(action, selectedOption) {
    if (!Array.isArray(action.targets)) return 0;
    const expanded = expandMultiTargetRequirements(action.targets || [], readX(action.instance_id, action.face, action.blitz, action.splice_ids));
    for (let i = 0; i < expanded.requirements.length; i += 1) {
      const req = expanded.requirements[i];
      if (!Array.isArray(req.options)) continue;
      for (const option of req.options) {
        if (selectedOption.player_id != null ? option.player_id === selectedOption.player_id : option.instance_id === selectedOption.instance_id) {
          return expanded.owners[i];
        }
      }
    }
    return 0;
  }

  function selectedKickerAction(action, kicked = readKicker(action.instance_id, action.face, action.splice_ids)) {
    const count = Array.isArray(kicked) ? kicked.length : kicked;
    if (!(count > 0)) return action;
    const selected = action.kicker_variant || action;
    if (action.squad_discard_cost) {
      const cost = action.squad_discard_cost;
      return { ...selected, discard_cost: { ...cost, count: count * cost.count } };
    }
    if (action.squad_exile_cost) {
      const cost = action.squad_exile_cost;
      return { ...selected, graveyard_exile_cost: { ...cost, count: count * cost.count } };
    }
    return selected;
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



  function mount(el) {
    root = el;
    // Resume from a gesture, before awaiting a game action's network reply.
    root.addEventListener('pointerdown', () => { void audio.unlock(); });
    root.addEventListener('keydown', () => { void audio.unlock(); });
  }

  /** Begin driving `sessionId`, rendering `initialView` immediately. */
  function start(sid, initialView) {
    const isNewSession = sid !== sessionId;
    if (isNewSession) {
      showStatics = false;
      staticsAside = false;
      resetChatSession();
      zoneOrder.clear();
      waitingChoiceAside = false;
    }
    sessionId = sid;
    stopped = false;
    applyView(initialView);
    restoreUiDraft(initialView);
    // A game just became the thing on screen — let the app shell fold its
    // side menu away so the board gets the full width (app.js). Once per
    // session, not on every repaint.
    if (isNewSession) {
      resolvedGhosts = [];
      resetPrioritySession();
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

  function applyView(data) {
    if (audioSession === sessionId) {
      for (const event of gameAudioEvents(audioView, data)) audio.play(event);
    } else audio.stop();
    audioSession = sessionId;
    audioView = data;
    const prevStack = view?.state?.stack || [];
    const samePriorSessionForStack = sessionId === lastDraftSessionId;
    view = data;
    updateRevealPopup(data);
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
    postUiDraft(assignments.length ? { kind: 'block', assignments } : null);
  }

  function persistCastTargetingDraft() {
    if (!sessionId) return;
    postUiDraft(castTargeting ? { kind: 'cast', castTargeting } : null);
  }

  // BUG-38: multiplayer supplies its own seat-checked draft route.
  function postUiDraft(draft) {
    if (transport.saveUiDraft) return transport.saveUiDraft(draft);
    return saveUiDraft(sessionId, view?.perspective ?? null, draft);
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
      let action = findTargetableAction(
        ct.instanceId, ct.send.type, ct.send.ability_index, ct.send.face, ct.send.mode,
        ct.send.pay_additional, ct.send.bargained, ct.send.evoke, ct.send.gift_opponent_id, ct.send.surge, ct.send.blitz, ct.send.alt_cost, ct.send.warp, ct.send.splice_ids, ct.send.free,
      );
      if (action) {
        action = selectedKickerAction(action, ct.send.kicked);
        const expanded = expandMultiTargetRequirements(action.targets || [], ct.x || 0);
        const sameShape = ct.isTapChoice || ct.isSacrificeChoice || ct.isDiscardChoice || ct.isGraveyardExileChoice || ct.isSacrificeCountChoice || ct.isReturnChoice || ct.isBlightChoice
          ? Array.isArray(ct.requirements)
          : expanded.requirements.length === (ct.requirements || []).length;
        if (sameShape && Number.isInteger(ct.reqIndex)) {
          castTargeting = ct;
          render();
        }
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
    if (action.type === 'cast_spell' && action.replicate == null) {
      action.replicate = readReplicate(action.instance_id, action.face, action.splice_ids);
    }
    // Never leave combat with an unsent selection. The first forward click
    // confirms it; the next click resumes priority/step advancement.
    if (attackDraft.size && ['advance_step', 'advance_to_decision', 'pass_priority', 'set_yield'].includes(action.type)
        && !view.state.stack.length) {
      await submitAttackers();
      return;
    }
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
        // was the auto-skip's own `pass_priority` attempt, the controller's
        // attempted-window guard
        // would otherwise stay set to a window that never actually got
        // passed — wedging the ⏭/auto-skip logic for the rest of the game
        // (nothing else ever resets it). Clearing it here lets the next
        // render retry instead of silently going inert.
        clearSkipAttempt();
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

  let boardGeometryCleanup = () => {};
  let cardMenuSerial = 0;

  function wireBoardGeometry() {
    boardGeometryCleanup();
    boardGeometryCleanup = installBoardGeometry({
      root,
      view: () => view,
      attackDraft,
      blockDraft,
    });
  }

  function render() {
    if (!root || !view) return;
    const previousChat = root.querySelector('.gf-chat-messages');
    const chatAtBottom = !previousChat || previousChat.scrollHeight - previousChat.scrollTop - previousChat.clientHeight <= CHAT_BOTTOM_THRESHOLD_PX;
    const chatScrollTop = previousChat?.scrollTop || 0;
    const s = view.state;
    // Keep the countdown length (a server setting) current before anything
    // reads it — `railTimerHtml`/`autoPassArmed` both do, and `render()`
    // runs before `syncAutoPass()`.
    updateTimerSeconds();
    const dummy = s.players.find((p) => p.is_dummy) || null;
    // The seat this client is playing (multiplayer; null in every solo mode
    // and for an observer). Their board is drawn *last* — i.e. nearest the
    // player, like sitting at a table — with the opponents above it.
    const seatId = view.perspective || null;
    const live = boardOrder(s.players, seatId);
    const actions = view.legal_actions || [];
    const gameOver = s.game_over;
    const pending = s.pending_choice;
    // The payer can use the normal card menus while the mana prompt is aside.
    const paymentMana = pending?.kind === 'amount_payment' && pending.resource === 'mana';
    syncAttackDraft(actions, s);

    // Index per-object actions for each card’s context menu and attack selection. `legal_actions` is already scoped server-side
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
    if (!SELECTION_KINDS.has(pending?.kind)) proliferateDraft = { key: null, ids: new Set() };
    if (!s.waiting_on_choice) waitingChoiceAside = false;
    if (!castTargeting) castTargetAside = false;
    updateTargetOverlays(s);
    updateAbilitySourceOverlays(s, pending);

    root.innerHTML = `
      <div class="goldfish${compactView ? ' compact-view' : ''}${(pending && !choiceAside) || (castTargeting && !castTargetAside) ? ' choosing' : ''}${pickablesForBoard().length ? ' picking-target' : ''}" style="--gf-scale: ${(getBoardScale() / 100).toFixed(2)}">
        <svg class="gf-connection-lines" aria-hidden="true"></svg>
        <aside class="gf-rail">
          <div class="gf-rail-turn">
            <span class="gf-turn" title="${escapeAttr(t('bd.turn.rule500', { n: s.internal_turn.number }))}">${escapeHtml(t('bd.turn.label', { n: s.turn_nr }))}</span>
            <span class="gf-step">${escapeHtml(labelPhase(s.current_phase))} · ${escapeHtml(labelStep(s.current_step))}</span>
            ${s.day_night ? `<span class="gf-daynight gf-daynight-${s.day_night}">${s.day_night === 'night' ? '🌙 Nacht' : '☀️ Tag'}</span>` : ''}
          ${interactivePriority() && view.perspective && !gameOver ? `<div class="gf-rail-priority-actions">${yieldButtonsHtml(busy || !!pending)}${passButtonHtml(busy || !!pending || !hasPriority())}</div>` : ''}
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

          ${renderPlanechase(s, actions, { t, escapeHtml, escapeAttr, renderOracleText })}

          ${gameOver ? gameOverHtml(s, seatId ? s.players.find((p) => p.id === seatId) : live[0]) : ''}
          ${statusHtml()}
          ${view.observer ? `<p class="server-status gf-observer-note">${escapeHtml(t('bd.observerNote'))}</p>` : ''}
          ${waitingOnChoiceHtml(s)}
          ${pending ? pendingChoiceHtml(pending, choiceAside) : ''}
          ${castTargeting ? castTargetModalHtml() : ''}
          ${showStatics ? staticEffectsModalHtml(s) : ''}
          ${revealPopupHtml()}

          ${attackerPanelHtml(actions, s)}
          ${blockerPanelHtml(actions, s)}

          ${boardsHtml(live, s, byInstance, paymentMana ? null : pending, seatId)}

          ${delayedTriggersPanelHtml(view)}
        </div>
      </div>
    `;
    wire();
    wireBoardGeometry();
    const chatList = root.querySelector('.gf-chat-messages');
    if (chatList) chatList.scrollTop = chatAtBottom ? chatList.scrollHeight : chatScrollTop;
    syncAutoPass();
    // A repaint mid-countdown rebuilds the bar at its inline default; catch
    // it up to the live remaining value straight away so it doesn't flash
    // back to full for up to a second.
    if (priority.autoPassRunning()) paintCountdown();
  }

  function staticEffectsButtonHtml() {
    return `<button type="button" data-statics-open aria-haspopup="dialog" aria-expanded="${showStatics}">🔍 ${escapeHtml(t('bd.bf.statics'))}</button>`;
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
          ${staticEffectsButtonHtml()}
          ${extra}
        </div>`;
    }
    // With interactive priority (RULE 117, shared games) the turn isn't
    // advanced by anyone deciding it should be — it moves when players
    // pass, so "Nächster Schritt" is replaced by "Passen" and the whole
    // toolbar keys off who holds priority rather than whose turn it is.
    if (interactivePriority()) return priorityControlsHtml(extra);

    // Whether *this* client may drive the turn. In a shared game only the
    // active player can (RULE 500.1, enforced server-side too); solo modes
    // have no perspective and always can.
    const myTurn = !view.perspective || view.state.active_player_id === actingSeat();
    return `
      <div class="gf-controls gf-rail-controls">
        <button id="gf-advance" type="button" class="primary" ${busy || gameOver || pending || !myTurn ? 'disabled' : ''}>${attackDraft.size ? escapeHtml(t('bd.attack.confirm', { count: attackDraft.size })) : t('bd.ctrl.advance')}</button>
        ${allowFastForward ? `<button id="gf-next-decision" type="button" title="${escapeAttr(t('bd.ctrl.nextDecisionTitle2'))}" ${busy || gameOver || pending || !myTurn ? 'disabled' : ''}>${t('bd.ctrl.nextDecision')}</button>` : ''}
        ${stackNonEmpty && !pending ? `<button type="button" data-action='${escapeAttr(JSON.stringify({ type: 'pass_priority' }))}'>${t('bd.ctrl.passResolveStack')}</button>` : ''}
        ${allowRewind ? `<button id="gf-rewind" type="button" ${busy || !view.can_rewind ? 'disabled' : ''}>${t('bd.ctrl.rewind')}</button>` : ''}
        ${staticEffectsButtonHtml()}
        ${extra}
      </div>`;
  }

  function waitingOnChoiceHtml(s) {
    const waiting = s.waiting_on_choice;
    if (!waiting) return '';
    const who = playerName(waiting.decider_id || waiting.player_id);
    const what = waiting.prompt ? ` (${escapeHtml(waiting.prompt)})` : '';
    const asideLabel = waitingChoiceAside ? t('bd.choice.asideShow') : t('bd.choice.asidePush');
    return `
      <div class="gf-modal-overlay gf-waiting-choice${waitingChoiceAside ? ' aside' : ''}">
        <div class="gf-modal" role="dialog" aria-label="${escapeAttr(who)}">
          <div class="gf-modal-head">
            <span class="gf-modal-icon">⏳</span>
            <div role="status"><h4>${escapeHtml(who)} trifft gerade eine Entscheidung${what} …</h4></div>
            <button type="button" class="gf-modal-aside" data-waiting-choice-aside title="${escapeAttr(t('bd.choice.asideTitle'))}">${asideLabel}</button>
          </div>
        </div>
      </div>`;
  }

  // MEC-51 / RULE 724: "Du kontrollierst den Zug von X" (Mindslaver, Sorin
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

  // RULE 508.1: choose the whole attack before tapping or firing triggers.
  function syncAttackDraft(actions, state) {
    const key = JSON.stringify([sessionId, state.internal_turn?.number, state.active_player_id, state.current_step]);
    if (key !== attackDraftKey || state.current_step !== 'declare_attackers' || state.game_over) {
      attackDraft.clear();
      attackMenuOpen.clear();
      attackDraftKey = key;
    }
    const offers = actions.filter(a => a.type === 'attack');
    for (const [iid, selection] of attackDraft) {
      const offer = offers.find(a => a.instance_id === iid);
      const legal = offer && (!selection.defender || (offer.legal_defenders || []).some(d =>
        JSON.stringify(defenderPayload(d)) === JSON.stringify(selection.defender)));
      if (!legal) attackDraft.delete(iid);
      else if (selection.enlist_ids) {
        const options = new Set((offer.enlist_options || []).map(o => o.instance_id));
        selection.enlist_ids = selection.enlist_ids.map(id => options.has(id) && !attackDraft.has(id) ? id : null);
      }
    }
  }

  function attackerPanelHtml(actions, state) {
    if (view.observer || state.pending_choice || state.stack.length || !actions.some(a => a.type === 'attack')) return '';
    const enlisted = new Set([...attackDraft.values()].flatMap(a => a.enlist_ids || []));
    const rows = actions.filter(a => a.type === 'attack' && attackDraft.has(a.instance_id)).flatMap(a => {
      const picks = attackDraft.get(a.instance_id).enlist_ids || [];
      return Array.from({ length: a.enlist_count || 0 }, (_, index) => {
        const options = a.enlist_options.filter(candidate => {
          const id = candidate.instance_id;
          return !attackDraft.has(id) && (!enlisted.has(id) || picks[index] === id);
        });
        if (!options.length) return '';
        return `<label class="gf-block-row">${escapeHtml(a.name)} · Enlist
          <select data-enlist-attacker="${a.instance_id}" data-enlist-index="${index}" ${busy ? 'disabled' : ''}>
            <option value="">${t('bd.attack.noEnlist')}</option>
            ${options.map(({ instance_id, name }) =>
              `<option value="${instance_id}"${picks[index] === instance_id ? ' selected' : ''}>${escapeHtml(name)}</option>`
            ).join('')}
          </select>
        </label>`;
      });
    }).join('');
    return `<section class="gf-block-panel">
      <h4>${t('bd.attack.heading')}</h4>
      <p class="hint">${t('bd.attack.hint')}</p>${rows}
      <div class="gf-controls">
        <button type="button" class="primary" data-attack-confirm ${busy || !attackDraft.size ? 'disabled' : ''}>${escapeHtml(t('bd.attack.confirm', { count: attackDraft.size }))}</button>
        <button type="button" data-attack-clear ${busy || !attackDraft.size ? 'disabled' : ''}>${t('bd.attack.clear')}</button>
      </div>
    </section>`;
  }

  async function submitAttackers() {
    if (busy || !attackDraft.size) return;
    const selected = [...attackDraft.values()];
    const tax = selected.reduce((sum, a) => sum + (a.attack_tax_amount || 0), 0);
    const life = selected.reduce((sum, a) => sum + (a.attack_life_amount || 0), 0);
    const cost = [tax && `{${tax}}`, life && t('bd.combatCost.life', { count: life })].filter(Boolean).join(' + ');
    if (cost && !window.confirm(t('bd.attackTax.confirm', { cost }))) return;
    await act({ type: 'declare_attackers', declarations: selected.map(a => ({
      instance_id: a.instance_ids[0], defender: a.defender, pay_attack_tax: true,
      enlist_ids: (a.enlist_ids || []).filter(Boolean),
    })) });
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
    const offers = (view?.legal_actions || []).filter((a) => a.type === 'declare_blockers');
    const tax = assignments.reduce((sum, { blocker }) =>
      sum + (offers.find((a) => a.instance_id === blocker)?.block_tax_amount || 0), 0);
    const life = assignments.reduce((sum, { blocker, attacker }) => sum + (offers
      .find(a => a.instance_id === blocker)?.legal_attackers.find(a => a.instance_id === attacker)?.life_cost || 0), 0);
    const cost = [tax && `{${tax}}`, life && t('bd.combatCost.life', { count: life })].filter(Boolean).join(' + ');
    if (cost && !window.confirm(t('bd.blockTax.confirm', { cost }))) return;
    await act({ type: 'declare_blockers', assignments, pay_block_tax: true });
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
  function knownLibraryHtml(p) {
    const known = (view.state.known_cards || []).filter(card => card.owner_id === p.id && card.zone === 'library')
      .sort((a, b) => a.library_position - b.library_position);
    if (!known.length) return '';
    return `<ol class="gf-known-library" aria-label="${escapeAttr(t('bd.reveal.library'))}">${known.map(card =>
      `<li value="${card.library_position}" data-hover-card="${escapeAttr(card.name)}">${escapeHtml(card.name)}</li>`
    ).join('')}</ol>`;
  }

  function libraryTopHtml(p, byInstance, pending) {
    if (!view.top_library_visible?.[p.id] || !p.library.length) return '';
    const top = p.library[p.library.length - 1];
    return `
      <p class="library-top-hint">${t('bd.libraryTop.visible')}</p>
      ${objGrid([top], '', byInstance, pending)}
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

  function wireEffectPopovers() {
    root.querySelectorAll('.gf-effects-pop').forEach((pop) => {
      const badge = root.querySelector(`[popovertarget="${CSS.escape(pop.id)}"]`);
      if (!badge) return;
      pop.addEventListener('toggle', (e) => {
        if (e.newState === 'open') positionEffectPopover(pop, badge);
      });
    });
  }

  // Event wiring is split by concern; `wire()` runs them in the original order after each repaint.
  function wireTurnControls() {
    root.querySelectorAll('[data-card-menu]').forEach(slot => {
      const open = (event) => {
        if (event.target.closest('.gf-card-menu')) return;
        event.preventDefault();
        const menu = document.getElementById(slot.dataset.cardMenu);
        if (!menu) return;
        root.querySelectorAll('.gf-card-menu:popover-open').forEach(other => { if (other !== menu) other.hidePopover(); });
        menu.showPopover();
        const bounds = menu.getBoundingClientRect();
        menu.style.left = `${Math.max(0, Math.min(event.clientX || slot.getBoundingClientRect().left, window.innerWidth - bounds.width))}px`;
        menu.style.top = `${Math.max(0, Math.min(event.clientY || slot.getBoundingClientRect().bottom, window.innerHeight - bounds.height))}px`;
      };
      slot.addEventListener('contextmenu', open);
      const tile = slot.querySelector('.card');
      tile.tabIndex = 0;
      tile.addEventListener('keydown', event => {
        if (event.key === 'ContextMenu' || (event.shiftKey && event.key === 'F10')) open(event);
      });
    });
    wireEffectPopovers();
    wireChatEvents();
    root.querySelector('#gf-advance')?.addEventListener('click', () => act({ type: 'advance_step' }));
    root.querySelector('#gf-next-decision')?.addEventListener('click', () => act({ type: 'advance_to_decision' }));
    root.querySelector('#gf-rewind')?.addEventListener('click', rewind);
    // Priority action below the phase display.
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
  }

  function wireBlocksAndExtras() {
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
  }

  function wireChoiceForms() {
    root.querySelectorAll('[data-blind-cast]').forEach(el => {
      el.addEventListener('click', () => {
        const form = el.closest('.gf-blind-sideboard');
        const mode = form.querySelector('[data-blind-mode]').value;
        act({type: 'cast_spell', instance_id: Number(form.querySelector('[data-blind-slot]').value),
          x: Number(form.querySelector('[data-blind-x]').value),
          face: form.querySelector('[data-blind-face]').value,
          ...(mode ? {mode: Number(mode) - 1} : {}),
          targets: [...form.querySelector('[data-blind-targets]').selectedOptions].map(o => JSON.parse(o.value))});
      });
    });
    root.querySelectorAll('[data-proliferate-option]').forEach(el => {
      el.addEventListener('change', () => {
        if (el.checked) proliferateDraft.ids.add(el.dataset.proliferateOption);
        else proliferateDraft.ids.delete(el.dataset.proliferateOption);
      });
    });
    root.querySelector('[data-proliferate-reset]')?.addEventListener('click', () => {
      proliferateDraft.ids = new Set(view.state.pending_choice.recommended_ids || []);
      render();
    });
    root.querySelector('[data-proliferate-clear]')?.addEventListener('click', () => {
      proliferateDraft.ids.clear();
      render();
    });
    root.querySelector('[data-proliferate-confirm]')?.addEventListener('click', () => {
      if (busy) return;
      act({ type: 'choose', selection_id: proliferateDraft.key, option_ids: [...proliferateDraft.ids] });
    });
    const measurementForm = root.querySelector('[data-physical-measurement]');
    if (measurementForm) {
      const input = measurementForm.querySelector('[data-measurement-value]');
      const submit = measurementForm.querySelector('[data-measurement-submit]');
      const error = measurementForm.querySelector('[data-measurement-error]');
      input.addEventListener('input', () => {
        measurementDraft.text = input.value;
        const valid = measurementValue(input.value, view.state.pending_choice) !== null;
        submit.disabled = busy || !valid;
        error.textContent = input.value && !valid ? t('bd.measurement.invalid') : '';
      });
      measurementForm.addEventListener('submit', event => {
        event.preventDefault();
        if (busy) return;
        const value = measurementValue(input.value, view.state.pending_choice);
        if (value === null) {
          error.textContent = t('bd.measurement.invalid');
          return;
        }
        act({ type: 'choose', option_id: value });
      });
    } else if (!['physical_property_measurement', 'physical_environment_measurement'].includes(view.state?.pending_choice?.kind)) {
      measurementDraft = { key: null, text: '' };
    }
    const choiceTextForm = root.querySelector('[data-choice-text]');
    if (choiceTextForm) {
      const input = choiceTextForm.querySelector('[data-choice-text-value]');
      const submit = choiceTextForm.querySelector('[data-choice-text-submit]');
      input.addEventListener('input', () => {
        choiceTextDraft.text = input.value;
        submit.disabled = busy || !input.value.trim();
      });
      choiceTextForm.addEventListener('submit', event => {
        event.preventDefault();
        const text = input.value.trim();
        if (busy || !text) return;
        act({ type: 'choose', free_text: true, option_id: text });
      });
    } else {
      choiceTextDraft = { key: null, text: '' };
    }
  }

  function wireBoardChrome() {
    // Battlefield 2-/3-row layout toggle (persisted, one checkbox per board).
    root.querySelectorAll('.gf-rows-toggle').forEach((el) => {
      el.addEventListener('change', (e) => {
        threeRows = e.target.checked;
        setCookie('gf_board_rows', threeRows ? '3' : '2', 365);
        render();
      });
    });

    const focusStatics = () => root.querySelector('.gf-statics-modal .gf-modal')?.focus();
    root.querySelector('[data-statics-open]')?.addEventListener('click', () => {
      showStatics = true;
      staticsAside = false;
      render();
      focusStatics();
    });
    const closeStatics = () => {
      showStatics = false;
      staticsAside = false;
      render();
      root.querySelector('[data-statics-open]')?.focus();
    };
    root.querySelector('[data-statics-close]')?.addEventListener('click', closeStatics);
    root.querySelector('[data-statics-aside]')?.addEventListener('click', () => {
      staticsAside = !staticsAside;
      render();
      focusStatics();
    });
    root.querySelector('.gf-statics-modal')?.addEventListener('keydown', event => {
      if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); closeStatics(); }
    });

    // Push a pending-choice popup aside (or bring it back).
    root.querySelector('[data-choice-aside]')?.addEventListener('click', () => {
      choiceAside = !choiceAside;
      render();
    });
    root.querySelector('[data-waiting-choice-aside]')?.addEventListener('click', () => {
      waitingChoiceAside = !waitingChoiceAside;
      render();
    });
  }

  function wireAttackDeclaration() {
    root.querySelectorAll('[data-enlist-attacker]').forEach(el => {
      el.addEventListener('change', () => {
        const selection = attackDraft.get(Number(el.dataset.enlistAttacker));
        const picks = selection.enlist_ids ||= [];
        picks[Number(el.dataset.enlistIndex)] = Number(el.value) || null;
        render();
      });
    });
    root.querySelectorAll('[data-attack-remove]').forEach(el => {
      el.addEventListener('click', () => {
        attackDraft.delete(Number(el.dataset.attackRemove));
        render();
      });
    });
    root.querySelector('[data-attack-clear]')?.addEventListener('click', () => {
      attackDraft.clear();
      render();
    });
    root.querySelector('[data-attack-confirm]')?.addEventListener('click', submitAttackers);

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
  }

  function wire() {
    wireTurnControls();
    wireBlocksAndExtras();
    wireChoiceForms();
    wireCardActionsAndDrag();
    wireBoardChrome();
    wireAttackDeclaration();
    wireCastForms();
    wireCostPayments();
  }

  function submitManaActivation(send) {
    const action = (view?.legal_actions || []).find(
      (a) => a.type === send.type && a.instance_id === send.instance_id && a.ability_index === send.ability_index,
    );
    const selectedOption = action?.options?.find((option) => option.index === send.option_index);
    if (selectedOption?.cost_land) send.cost_land = selectedOption.cost_land;
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

  function readX(instanceId, face, blitz, spliceIds) {
    const input = root.querySelector(`[data-x-input="${xKey(instanceId, face, blitz, spliceIds)}"]`);
    return Math.max(0, Math.floor(Number(input?.value) || 0));
  }

  // RULE 702.33b/d (ENG-62): the checked kicker costs of a two-cost spell as a list of indices, or undefined when the
  // spell has the single count field.
  function readKickerCosts(instanceId, face, spliceIds) {
    const boxes = [...root.querySelectorAll(`[data-kicker-cost-input="${kickerKey(instanceId, face, spliceIds)}"]`)];
    return boxes.length ? boxes.filter((box) => box.checked).map((box) => Number(box.dataset.costIndex)) : undefined;
  }

  // What goes on the wire as `kicked`: the index list for a two-cost spell, else the count.
  function readKickerAnnouncement(instanceId, face, spliceIds) {
    return readKickerCosts(instanceId, face, spliceIds) ?? readKicker(instanceId, face, spliceIds);
  }

  function readKicker(instanceId, face, spliceIds) {
    const costs = readKickerCosts(instanceId, face, spliceIds);
    if (costs) return costs.length;
    const input = root.querySelector(`[data-kicker-input="${kickerKey(instanceId, face, spliceIds)}"]`);
    return Math.max(0, Math.floor(Number(input?.value) || 0));
  }

  function readReplicate(instanceId, face, spliceIds) {
    const group = root.querySelector(`[data-replicate-group="${kickerKey(instanceId, face, spliceIds)}"]`);
    const inputs = [...(group?.querySelectorAll('[data-replicate-input]') || [])];
    return inputs.length ? inputs.map((input) => Math.max(0, Math.floor(Number(input.value) || 0))) : undefined;
  }

  // Kicker's own {X} (RULE 702.33b, PAR-7 — Emblazoned Golem-shaped): a
  // second, independent value from the spell's own X, keyed/read the same way.
  function readKickerX(instanceId, face, spliceIds) {
    const input = root.querySelector(`[data-kicker-x-input="${kickerKey(instanceId, face, spliceIds)}"]`);
    return Math.max(0, Math.floor(Number(input?.value) || 0));
  }

  // --- Rendering helpers ------------------------------------------------

  // The passive "goldfish" opponent: a compact strip with its life (the
  // thing you're racing down), plus hidden hand/graveyard/library counts.
  function opponentStripHtml(opp) {
    return `
      <div class="gf-opponent" data-player-id="${escapeAttr(opp.id)}">
        <span class="gf-opp-name">🐟 ${escapeHtml(opp.name)}</span>
        <span class="gf-opp-life" title="${escapeAttr(t('bd.opp.lifeTitle'))}">❤️ ${opp.life}</span>
        ${commanderDamageHtml(opp.commander_damage, view)}
        <span title="${escapeAttr(t('bd.opp.handTitle'))}">🖐️ ${opp.hand_count ?? opp.hand?.length ?? 0}</span>
        <span title="${escapeAttr(t('bd.opp.graveTitle'))}">⚰️ ${opp.graveyard?.length ?? 0}</span>
        <span title="${escapeAttr(t('bd.opp.libraryTitle'))}">📚 ${opp.library_count ?? 0}</span>
        <span class="gf-opp-tag">${t('bd.opp.passive')}</span>
      </div>`;
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

  function staticEffectsModalHtml(s) {
    return `<div class="gf-modal-overlay gf-statics-modal${staticsAside ? ' aside' : ''}">
      <div class="gf-modal" role="dialog" aria-modal="${!staticsAside}" aria-label="${escapeAttr(t('bd.bf.statics'))}" tabindex="-1">
        <div class="gf-modal-head">
          <div><h4>${escapeHtml(t('bd.bf.statics'))}</h4></div>
          <button type="button" class="gf-modal-aside" data-statics-aside title="${escapeAttr(t('bd.choice.asideTitle'))}">${escapeHtml(t(staticsAside ? 'bd.choice.asideShow' : 'bd.choice.asidePush'))}</button>
          <button type="button" data-statics-close aria-label="${escapeAttr(t('bd.statics.close'))}">×</button>
        </div>
        ${staticEffectsPanelHtml(view, s)}
      </div>
    </div>`;
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
    boardGeometryCleanup();
    audio.stop();
    audioView = null;
    audioSession = null;
    priority.stop();
    sessionId = null;
    if (root) delete root.dataset.bugReportSession;
    view = null;
    resolvedGhosts = [];
    stopped = true;
  }

  return { mount, start, refresh, setAssets, stop };
}
