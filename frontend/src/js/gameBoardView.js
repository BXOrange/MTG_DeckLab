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
import { sendGameAction, rewindGame, cardImageUrl, saveUiDraft, GENERIC_TOKEN_KEY } from './api.js';
import { getCookie, setCookie } from './cookies.js';
import { getBoardScale, onBoardScaleChange } from './boardScale.js';
import { bannerColorLabel, bannerStyle } from './bannerColors.js';
import { MANA_SYMBOL_EMOJI, renderOracleText } from './cardTile.js';
import { getBotSpeedMs, getShowOpponentHand, getCompactView, saveSettings } from './settings.js';
import { t, tPlural } from './i18n.js';
import { setHeaderMessage } from './headerMessage.js';

import { boardOrder, createBoardLayout, planechaseHtml as renderPlanechase } from './gameBoard/boardLayout.js';
import { wireBoardGeometry as installBoardGeometry } from './gameBoard/boardGeometry.js';
import { createBoardChat } from './gameBoard/boardChat.js';
import { createPriorityController } from './gameBoard/priorityController.js';
import { createPlayerBoardRenderer } from './gameBoard/playerBoards.js';
import { escapeHtml, escapeAttr } from './gameBoard/html.js';
import { STEP_LABELS, labelPhase, labelStep, SELECTION_KINDS, TARGET_CHOICE_KINDS } from './gameBoard/labels.js';
import { sameActivationMode, exileCastableInfo, keywordAbbrev } from './gameBoard/cardHints.js';
import { expandMultiTargetRequirements, findTargetOptionForAction, resolvedDamageDivisions, targetOptionPayload, defenderPayload, actionHasCostPick, xKey, kickerKey, powerTapTotal } from './gameBoard/castForm.js';
import { isPlayableCardAction, dragTargetsForActions, findDragTarget } from './gameBoard/dragDrop.js';
import { stackItemSig, ghostItemName, syntheticStackItemFromMoveLabel } from './gameBoard/stackView.js';
import { opponentHandToggleHtml, zoneListHtml, restrictedManaHtml, positionEffectPopover, measurementValue, triggerOptionKey } from './gameBoard/miscHtml.js';
import { effectSummaryHtml, castTargetHtml, unavailableCardActionsHtml, manaPotentialHtml } from './gameBoard/cardForms.js';
import { staticEffectsPanelHtml, playerCountersHtml, commanderDamageHtml } from './gameBoard/playerPanels.js';
import { cardActionButtons } from './gameBoard/cardActions.js';
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

  // `objs` in the player's own drag-and-drop order for `zoneKey`; cards the
  // order doesn't know yet (just drawn / entered) go to the end.
  function orderedByLocal(zoneKey, objs) {
    const byId = new Map(objs.map((o) => [o.instance_id, o]));
    const order = (zoneOrder.get(zoneKey) || []).filter((id) => byId.has(id));
    for (const o of objs) if (!order.includes(o.instance_id)) order.push(o.instance_id);
    zoneOrder.set(zoneKey, order);
    return order.map((id) => byId.get(id));
  }
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
  function dragActionsForInstance(instanceId) {
    if (!latestByInstance || !latestByInstance[instanceId]) return [];
    return latestByInstance[instanceId].filter(isPlayableCardAction).map((action) => selectedKickerAction(action)).filter((action) => !action.locked);
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
    return kicked > 0 && action.kicker_variant ? action.kicker_variant : action;
  }

  function prepareCastTargeting(action, selectedOption = null) {
    action = selectedKickerAction(action);
    const requirements = action.targets || [];
    const expanded = expandMultiTargetRequirements(requirements, readX(action.instance_id, action.face, action.blitz, action.splice_ids));
    const send = {
      type: action.type,
      instance_id: action.instance_id,
      face: action.face,
      mode: action.mode,
      ability_index: action.ability_index,
    };
    if (action.has_x) {
      send.x = readX(action.instance_id, action.face, action.blitz, action.splice_ids);
    }
    send.replicate = readReplicate(action.instance_id, action.face, action.splice_ids);
    if (action.alt_cost) send.alt_cost = true;
    if (action.free) send.free = true;
    if (action.warp) send.warp = true;
    if (action.evoke) send.evoke = true;
    if (action.surge) send.surge = true;
    if (action.blitz != null) send.blitz = action.blitz;
    if (action.has_kicker || action.kicked) {
      send.kicked = readKicker(action.instance_id, action.face, action.splice_ids);
      if (action.kicker_has_x) send.kicker_x = readKickerX(action.instance_id, action.face, action.splice_ids);
    }
    if (action.pay_additional) send.pay_additional = true;
    if (action.bargained) send.bargained = true;
    if (action.gift_opponent_id) send.gift_opponent_id = action.gift_opponent_id;
    if (action.splice_ids?.length) send.splice_ids = action.splice_ids;
    castTargeting = {
      instanceId: action.instance_id,
      damageDivisions: resolvedDamageDivisions(action.damage_divisions, send.x || 0),
      divisionRequirements: requirements,
      requirements: expanded.requirements,
      owners: expanded.owners,
      reqIndex: 0,
      targets: [],
      groups: Array.from({ length: expanded.groupCount }, () => []),
      x: readX(action.instance_id, action.face, action.blitz, action.splice_ids),
      send,
      excludePicked: expanded.excludePicked,
      excludeControllers: expanded.excludeControllers,
    };
    if (selectedOption) {
      const owner = requirementOwnerIndexForOption(action, selectedOption);
      const target = targetOptionPayload(selectedOption);
      castTargeting.targets.push(target);
      castTargeting.groups[owner].push(target);
      castTargeting.reqIndex = 1;
    }
    finishCastIfReady();
  }

  function executeDroppedAction(target) {
    if (!dragSource || !target) return;
    const actions = dragActionsForInstance(dragSource.instanceId);
    if (!actions.length) return;

    // RULE 700.2: a drop must not silently announce the first mode. Show
    // all server-provided modes, including ones that need targets elsewhere.
    if (actions.some(a => (a.type === 'cast_spell' || a.type === 'activate_ability') && a.mode != null)) {
      const slot = root?.querySelector(`[data-card-menu][data-instance-id="${CSS.escape(dragSource.instanceId)}"]`);
      slot?.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true }));
      return;
    }

    if (target.type === 'battlefield') {
      const action = actions.find((a) => a.type === 'play_land'
        || ((a.type === 'cast_spell' || a.type === 'activate_ability') && !a.requires_target));
      if (!action) return;
      if (action.graveyard_exile_cost) {
        prepareCastTargeting(action);
        return;
      }
      act({ type: action.type, instance_id: action.instance_id, face: action.face, mode: action.mode, ability_index: action.ability_index, warp: action.warp, x: readX(action.instance_id, action.face, action.blitz, action.splice_ids) });
      return;
    }

    const action = actions.find((a) => findTargetOptionForAction(a, target.instanceId, target.playerId));
    if (!action) return;
    const option = findTargetOptionForAction(action, target.instanceId, target.playerId);
    if (!option) return;

    if (action.targets && action.targets.length <= 1 && !action.damage_divisions?.length && !action.kicker_variant
        && !actionHasCostPick(action)) {
      const send = {
        type: action.type,
        instance_id: action.instance_id,
        face: action.face,
        mode: action.mode,
        ability_index: action.ability_index,
      };
      if (action.has_x) {
        send.x = readX(action.instance_id, action.face, action.blitz, action.splice_ids);
      }
      if (action.warp) send.warp = true;
      if (action.evoke) send.evoke = true;
      if (action.surge) send.surge = true;
      if (action.blitz != null) send.blitz = action.blitz;
      if (action.has_kicker) {
        send.kicked = readKicker(action.instance_id, action.face, action.splice_ids);
        if (action.kicker_has_x) send.kicker_x = readKickerX(action.instance_id, action.face, action.splice_ids);
      }
      if (action.pay_additional) send.pay_additional = true;
      if (action.bargained) send.bargained = true;
      if (action.gift_opponent_id) send.gift_opponent_id = action.gift_opponent_id;
      if (action.free) send.free = true;
      if (action.alt_cost) send.alt_cost = true;
      if (action.splice_ids?.length) send.splice_ids = action.splice_ids;
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
  };
  const {
    playerName,
    targetControllerId,
    targetControllerChipHtml,
    pendingChoiceHtml,
    proliferateChoiceHtml,
    graveyardReplacementHtml,
    physicalMeasurementHtml,
    simpleChoiceButtonsHtml,
    choiceTextHtml,
    clashChoiceHtml,
    replacementOrderHtml,
    triggerOrderHtml,
  } = createChoiceRenderer(boardCtx);


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

          ${boardsHtml(live, s, byInstance, pending, seatId)}

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
    }
  }

  function attackerPanelHtml(actions, state) {
    if (view.observer || state.pending_choice || state.stack.length || !actions.some(a => a.type === 'attack')) return '';
    return `<section class="gf-block-panel">
      <h4>${t('bd.attack.heading')}</h4>
      <p class="hint">${t('bd.attack.hint')}</p>
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
    if (tax && !window.confirm(t('bd.attackTax.confirm', { cost: `{${tax}}` }))) return;
    await act({ type: 'declare_attackers', declarations: selected.map(a => ({
      instance_id: a.instance_ids[0], defender: a.defender, pay_attack_tax: true,
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
    if (tax > 0 && !window.confirm(t('bd.blockTax.confirm', { cost: `{${tax}}` }))) return;
    await act({ type: 'declare_blockers', assignments, pay_block_tax: true });
  }

  // A hand the server redacted (RULE 400.2 — an opponent's hand never
  // leaves the server, `services/game_session.py`) arrives as an empty
  // `hand` plus a non-zero `hand_count`; draw that many card backs so the
  // board still shows *how much* they're holding. A genuinely empty hand
  // has `hand_count === 0` and falls through to the normal "leer".
  function handHtml(p, byInstance, pending, isOwn = true) {
    const count = p.hand_count != null ? p.hand_count : p.hand.length;
    if (!isOwn && p.hand.length && count > p.hand.length) {
      const hidden = count - p.hand.length;
      const backs = getShowOpponentHand()
        ? `<div class="card-grid">${Array.from({ length: hidden }, () => `<div class="gf-card-slot">${faceDownCardHtml()}</div>`).join('')}</div>`
        : `<p class="empty-state gf-hand-hidden">${escapeHtml(tPlural('bd.hand.hiddenCount', hidden))}</p>`;
      return objGrid(p.hand, '–', byInstance, pending) + backs;
    }
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
    if (!isOwn || !p.hand.length) return objGrid(p.hand, 'leer', byInstance, pending);
    const imageCache = getState().imageCache;
    return `<div class="card-grid" data-order-zone="${escapeAttr(`hand:${p.id}`)}">${orderedByLocal(`hand:${p.id}`, p.hand).map(o =>
      objCard(o, imageCache, pending ? [] : byInstance[o.instance_id] || [], true)
    ).join('')}</div>`;
  }

  // One face-down card: the player's own chosen sleeve if they uploaded one
  // (Einstellungen tab, `setAssets`), otherwise a plain patterned back.
  function faceDownCardHtml(label = t('bd.hand.faceDownAlt')) {
    if (assetsSleeveImageUrl) {
      return `<div class="card has-image gf-face-down"><img src="${escapeAttr(assetsSleeveImageUrl)}" alt="${escapeAttr(label)}" /></div>`;
    }
    return `<div class="card gf-face-down" title="${escapeAttr(label)}"></div>`;
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

  // The candidates of the current RULE 115 target round, after the
  // per-round exclusions (same permanent twice, same controller twice).
  function castTargetOptions() {
    if (!castTargeting) return [];
    const req = castTargeting.requirements[castTargeting.reqIndex] || {};
    let options = req.options || [];
    if (req.different_names) {
      const picked = castTargeting.targets.map((target) => req.options.find((option) => option.instance_id === target.instance_id));
      const completes = (prefix) => {
        const ids = new Set();
        let names = new Set();
        for (const option of prefix) {
          if (!option?.names?.length || ids.has(option.instance_id) || option.names.some((name) => names.has(name))) return false;
          ids.add(option.instance_id);
          names = new Set([...names, ...option.names]);
        }
        const extend = (start, needed, usedNames) => {
          if (needed <= 0) return true;
          for (let i = start; i < req.options.length; i += 1) {
            const option = req.options[i];
            if (ids.has(option.instance_id) || !option.names?.length || option.names.some((name) => usedNames.has(name))) continue;
            if (extend(i + 1, needed - 1, new Set([...usedNames, ...option.names]))) return true;
          }
          return false;
        };
        return extend(0, castTargeting.requirements.length - prefix.length, names);
      };
      options = options.filter((option) => completes([...picked, option]));
    }
    if (req.matching_names && castTargeting.targets.length) {
      const picked = castTargeting.targets.map((target) => req.options.find((option) => option.instance_id === target.instance_id));
      options = options.filter((option) => {
        let common = option.names || [];
        for (const prior of picked) common = common.filter((name) => prior?.names?.includes(name));
        return common.length > 0;
      });
    }
    if (req.shared_creature_type && castTargeting.targets.length) {
      const picked = castTargeting.targets.map((target) => req.options.find((option) => option.instance_id === target.instance_id));
      options = options.filter((option) => {
        let common = option.creature_types || [];
        for (const prior of picked) common = common.filter((kind) => prior?.creature_types?.includes(kind));
        return common.length > 0;
      });
    }
    if (req.shared_color && castTargeting.targets.length) {
      const picked = castTargeting.targets.map((target) => req.options.find((option) => option.instance_id === target.instance_id));
      options = options.filter((option) => {
        let common = option.colors || [];
        for (const prior of picked) common = common.filter((color) => prior?.colors?.includes(color));
        return common.length > 0;
      });
    }
    if (castTargeting.excludePicked || req.distinct_from_others) {
      // A "tap N untapped <type>s you control" cost (RULE 602.1): the same
      // permanent can't pay two of the N picks. `distinct_from_others` is
      // RULE 109.5's "**another** target creature" (Pit Fight, Ulvenwald
      // Tracker) — same exclusion, but across *requirements*: whatever the
      // other half of the clause already chose is off this round's pool.
      // A player option has a `player_id` and no `instance_id`, so the key names which of the two it is
      // (ENG-52: "any other target" can be a player; `undefined` must not exclude every player).
      const targetKey = (o) => (o.player_id != null ? `p:${o.player_id}` : `i:${o.instance_id}`);
      const pickedKeys = new Set(castTargeting.targets.map(targetKey));
      options = options.filter((o) => !pickedKeys.has(targetKey(o)));
    }
    if (castTargeting.excludeControllers) {
      // Run Away Together/Protector of the Wastes-shaped "controlled by
      // different players": once one round has picked a permanent, no
      // later round may pick another one sharing that controller.
      const pickedControllers = new Set((castTargeting.pickedControllers || []).filter((c) => c != null));
      options = options.filter((o) => !pickedControllers.has(o.controller_id));
    }
    if (req.same_graveyard) {
      const owner = castTargeting.owners?.[castTargeting.reqIndex];
      const picked = castTargeting.groups?.[owner] || [];
      const first = req.options.find((o) => o.instance_id === picked[0]?.instance_id);
      if (first) options = options.filter((o) => o.graveyard_owner_id === first.graveyard_owner_id);
    }
    for (const [field, limit] of [['power', req.total_power_max], ['mana_value', req.total_mana_value_max]]) {
      if (limit == null) continue;
      const owner = castTargeting.owners?.[castTargeting.reqIndex];
      const picked = castTargeting.groups?.[owner] || [];
      const used = picked.reduce((sum, target) => sum + (req.options.find((o) => o.instance_id === target.instance_id)?.[field] || 0), 0);
      options = options.filter((o) => used + (o[field] || 0) <= limit);
    }
    return options;
  }

  // One RULE 115 pick, whether it came from the popup button or a click on
  // the board (VIS-14). `target === null` is the "no target" decline.
  function pickCastTarget({ instance_id: iid, target, controller_id: controllerId }) {
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
      // per-round filtering — see `castTargetOptions`.
      (castTargeting.pickedControllers ||= []).push(controllerId ?? null);
    }
    const requirement = castTargeting.requirements[castTargeting.reqIndex];
    if (target === null && requirement?.any_number) {
      const owner = castTargeting.owners[castTargeting.reqIndex];
      while (castTargeting.owners[castTargeting.reqIndex] === owner) castTargeting.reqIndex += 1;
      finishCastIfReady();
      return;
    }
    castTargeting.reqIndex = target === null && (castTargeting.isSacrificeCountChoice || castTargeting.isPowerTapChoice)
      ? castTargeting.requirements.length : castTargeting.reqIndex + 1;
    finishCastIfReady();
  }

  // VIS-14: what can be clicked on the board right now because the target
  // popup is pushed aside — `{instanceId | playerId, activate}` per legal
  // candidate. Covers both target UIs: the cast/activate picker and the
  // `trigger_target` pending choice. Cost choices (tap/sacrifice/discard)
  // are not targets and stay popup-only.
  function pickablesForBoard() {
    const out = [];
    if (castTargeting && castTargetAside && !castTargeting.isTapChoice
        && !castTargeting.isSacrificeChoice && !castTargeting.isDiscardChoice && !castTargeting.isReturnChoice && !castTargeting.isBlightChoice) {
      for (const o of castTargetOptions()) {
        const payload = { instance_id: castTargeting.instanceId, target: targetOptionPayload(o), controller_id: o.controller_id ?? null };
        out.push({ instanceId: o.instance_id, playerId: o.player_id, activate: () => pickCastTarget(payload) });
      }
    }
    const pending = view?.state?.pending_choice;
    if (pending && choiceAside && TARGET_CHOICE_KINDS.has(pending.kind)) {
      const players = new Set((view.state.players || []).map((pl) => pl.id));
      for (const opt of pending.options || []) {
        if (opt.id === 'decline' || opt.id === 'do') continue;
        const action = opt.action || { type: 'choose', option_id: opt.id, instance_id: opt.instance_id, name: opt.label };
        out.push({
          instanceId: opt.instance_id,
          playerId: opt.instance_id == null && players.has(opt.id) ? opt.id : undefined,
          activate: () => act(action),
        });
      }
    }
    return out;
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

  function wireCardActionsAndDrag() {
    root.querySelectorAll('[data-action]').forEach((el) => {
      el.addEventListener('click', () => {
        const action = JSON.parse(el.dataset.action);
        if (action.type === 'declare_attackers') {
          const iid = action.instance_ids[0];
          attackDraft.set(iid, action);
          attackMenuOpen.delete(iid);
          render();
          return;
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
        // A drop on a specific valid target (equip onto a creature) is a real
        // game action; any other drop inside the card's own zone only re-sorts
        // the local presentation order.
        const zoneEl = e.target.closest('[data-order-zone]');
        if (dragSource && zoneEl && zoneEl.dataset.orderZone === dragSource.zone
            && !['instance', 'player'].includes(maybeReadDropTargetData(e.target)?.type)) {
          e.preventDefault();
          const order = zoneOrder.get(dragSource.zone) || [];
          let targetSlot = e.target.closest('[data-instance-id]');
          // Dropped on an attachment: its host is what sits in the row.
          // `dataset` values are strings, instance ids on the wire may be numbers.
          const indexOfId = (id) => order.findIndex((known) => String(known) === String(id));
          if (targetSlot && indexOfId(targetSlot.dataset.instanceId) < 0) {
            targetSlot = targetSlot.closest('.gf-attach-group')?.querySelector('[data-instance-id]') || null;
          }
          const targetId = targetSlot?.dataset.instanceId;
          const from = indexOfId(dragSource.instanceId);
          const to = targetId ? indexOfId(targetId) : order.length - 1;
          if (from >= 0 && to >= 0 && from !== to) {
            order.splice(to, 0, order.splice(from, 1)[0]);
          }
          dragSource = null;
          clearDragHighlights();
          render();
          return;
        }
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
        dragSource = {
          instanceId,
          playerId: slot.closest('[data-player-id]')?.dataset.playerId || null,
          zone: slot.closest('[data-order-zone]')?.dataset.orderZone || null,
        };
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

  function wireCastForms() {
    // {X} spells read the announced value from the adjacent number input at
    // click time rather than baking it into a static data-action attribute.
    root.querySelectorAll('[data-replicate-group] input').forEach((input) => {
      input.addEventListener('input', () => {
        const key = input.closest('[data-replicate-group]').dataset.replicateGroup;
        root.querySelectorAll(`[data-replicate-group="${key}"] [data-replicate-input="${input.dataset.replicateInput}"]`)
          .forEach((other) => { other.value = input.value; });
      });
    });

    root.querySelectorAll('[data-cast-x]').forEach((el) => {
      el.addEventListener('click', () => {
        const { iid, face, mode, entwine, warp, evoke, surge, blitz, pay_additional, bargained, gift_opponent_id, splice_ids, free, alt_cost } = JSON.parse(el.dataset.castX);
        const x = readX(iid, face, blitz, splice_ids);
        const kicked = readKicker(iid, face, splice_ids);
        const kicker_x = readKickerX(iid, face, splice_ids);
        act({ type: 'cast_spell', instance_id: iid, x, face, kicked, kicker_x, mode, entwine, warp, evoke, surge, blitz, pay_additional, bargained, gift_opponent_id, splice_ids, free, alt_cost });
      });
    });

    root.querySelectorAll('[data-suspend-x]').forEach((el) => {
      el.addEventListener('click', () => {
        const iid = Number(el.dataset.suspendX);
        act({ type: 'suspend', instance_id: iid, x: readX(iid, 'suspend') });
      });
    });

    root.querySelectorAll('[data-tap-x]').forEach((el) => {
      el.addEventListener('click', () => {
        const { iid, ability_index, option_index } = JSON.parse(el.dataset.tapX);
        submitManaActivation({ type: 'tap_for_mana', instance_id: iid, ability_index, option_index, x: readX(iid, null) });
      });
    });

    root.querySelectorAll('[data-mana-choice-activate]').forEach((el) => {
      el.addEventListener('click', () => {
        const info = JSON.parse(el.dataset.manaChoiceActivate);
        const iid = Number(info.iid);
        const option_index = Number(el.closest('.gf-mana-choice')?.querySelector('[data-mana-option]')?.value);
        const send = { type: info.type, instance_id: iid, ability_index: info.ability_index, option_index };
        if (info.has_x) send.x = readX(iid, null);
        if (info.type === 'tap_for_mana') {
          submitManaActivation(send);
        } else {
          act(send);
        }
      });
    });

    root.querySelectorAll('[data-activate-x]').forEach((el) => {
      el.addEventListener('click', () => {
        const { iid, ability_index, mode } = JSON.parse(el.dataset.activateX);
        const x = readX(iid, null);
        const action = (view?.legal_actions || []).find(a => a.type === 'activate_ability'
          && a.instance_id === Number(iid) && a.ability_index === ability_index
          && sameActivationMode(a, mode));
        if (action?.graveyard_exile_cost) {
          prepareCastTargeting(action);
          return;
        }
        if (action?.reveal_cost || action?.counter_cost) {
          // PAR-247: an announced X that is paid with chosen cards (Martyr of Ashes) goes through the cost pickers.
          castTargeting = {
            instanceId: Number(iid), requirements: [], reqIndex: 0, targets: [], x,
            send: { type: 'activate_ability', instance_id: iid, ability_index, mode, x },
          };
          finishCastIfReady();
          return;
        }
        act({ type: 'activate_ability', instance_id: iid, ability_index, mode, x });
      });
    });

    root.querySelectorAll('[data-cast-target-start]').forEach((el) => {
      el.addEventListener('click', () => {
        const info = JSON.parse(el.dataset.castTargetStart);
        const iid = Number(info.iid);
        let action = findTargetableAction(
          iid, info.type, info.ability_index, info.face, info.mode,
          info.pay_additional, info.bargained, info.evoke, info.gift_opponent_id, info.surge, info.blitz, info.alt_cost, info.warp, info.splice_ids, info.free,
        );
        if (!action) return;
        const kicked = action.has_kicker ? readKicker(iid, info.face, info.splice_ids) : 0;
        action = selectedKickerAction(action, kicked);
        if (action.locked) {
          setStatus(action.lock_reason || t('bd.cast.noValidTarget'), 'error');
          render();
          return;
        }
        const x = action.has_x ? readX(iid, info.face, info.blitz, info.splice_ids) : 0;
        const kicker_x = action.kicker_has_x ? readKickerX(iid, info.face, info.splice_ids) : 0;
        const send = info.type === 'activate_ability'
          ? { type: 'activate_ability', instance_id: iid, ability_index: info.ability_index, mode: info.mode, name: action.name }
          : {
            type: 'cast_spell', instance_id: iid, name: action.name, face: info.face, kicked, kicker_x,
            replicate: readReplicate(iid, info.face, info.splice_ids),
            mode: info.mode, entwine: info.entwine, alt_cost: action.alt_cost, free: action.free, warp: action.warp, evoke: action.evoke, surge: action.surge, blitz: action.blitz, pay_additional: action.pay_additional,
            bargained: action.bargained, gift_opponent_id: action.gift_opponent_id, splice_ids: action.splice_ids,
          };
        const {
          requirements, owners, groupCount, excludePicked, excludeControllers,
        } = expandMultiTargetRequirements(action.targets || [], x);
        castTargeting = {
          instanceId: iid, requirements, owners, reqIndex: 0, targets: [], x, send,
          damageDivisions: resolvedDamageDivisions(action.damage_divisions, x), divisionRequirements: action.targets,
          groups: Array.from({ length: groupCount }, () => []),
          excludePicked, excludeControllers,
        };
        finishCastIfReady();
      });
    });

    root.querySelectorAll('[data-damage-requirement]').forEach((input) => {
      input.addEventListener('input', () => {
        if (!castTargeting) return;
        const index = input.dataset.damageRequirement;
        const inputs = [...root.querySelectorAll(`[data-damage-requirement="${index}"]`)];
        (castTargeting.damageDraft ||= {})[index] = inputs.map((field) => field.value);
        persistCastTargetingDraft();
      });
    });

    root.querySelector('[data-damage-confirm]')?.addEventListener('click', () => {
      const ct = castTargeting;
      if (!ct) return;
      const allocations = {};
      let valid = true;
      for (const division of ct.damageDivisions || []) {
        const index = division.requirement_index;
        const inputs = [...root.querySelectorAll(`[data-damage-requirement="${index}"]`)];
        const values = inputs.map((input) => input.value === '' ? NaN : Number(input.value));
        if (values.length !== (ct.groups?.[index] || []).length
            || values.some((value) => !Number.isInteger(value) || value < division.min_each)
            || (values.length > 0 && values.reduce((sum, value) => sum + value, 0) !== division.total)) valid = false;
        allocations[index] = values;
      }
      if (!valid) {
        root.querySelector('[data-damage-error]').textContent = 'Bitte den gesamten Schaden in ganzen Zahlen auf alle gewählten Ziele verteilen.';
        return;
      }
      ct.allocatedDamage = allocations;
      finishCastIfReady();
    });

    root.querySelectorAll('[data-cast-target-pick]').forEach((el) => {
      el.addEventListener('click', () => pickCastTarget(JSON.parse(el.dataset.castTargetPick)));
    });

    // VIS-14: push the target popup aside / bring it back.
    root.querySelector('[data-cast-target-aside]')?.addEventListener('click', () => {
      castTargetAside = !castTargetAside;
      render();
    });
    wirePickTargets();

    root.querySelectorAll('[data-cast-target-cancel]').forEach((el) => {
      el.addEventListener('click', () => {
        castTargeting = null;
        persistCastTargetingDraft();
        render();
      });
    });
  }

  function wireCostPayments() {
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

    root.querySelectorAll('[data-power-tap-start]').forEach((el) => {
      el.addEventListener('click', () => {
        const info = JSON.parse(el.dataset.powerTapStart);
        const action = view.legal_actions.find((a) => a.type === 'activate_ability'
          && a.instance_id === info.instance_id && a.ability_index === info.ability_index);
        if (action) prepareCastTargeting(action);
      });
    });

    root.querySelectorAll('[data-tap-choice-start]').forEach((el) => {
      el.addEventListener('click', () => {
        const info = JSON.parse(el.dataset.tapChoiceStart);
        const iid = Number(info.iid);
        const option_index = info.option_from_select
          ? Number(el.closest('.gf-mana-choice')?.querySelector('[data-mana-option]')?.value)
          : info.option_index;
        const action = (view?.legal_actions || []).find(
          (a) => a.type === info.type && a.instance_id === iid && a.ability_index === info.ability_index
            && sameActivationMode(a, info.mode),
        );
        if (!action || !(action.tap_cost || action.exile_cost)) return;
        const { count, options } = action.tap_cost || action.exile_cost;
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
          label: action.exile_cost ? t('bd.exile.permanent') : action.tap_cost?.untap ? t('bd.untap.permanent') : 'zu tappende Kreatur', options, optional: false,
          shared_creature_type: action.tap_cost?.shared_creature_type,
        }));
        const send = info.type === 'activate_ability'
          ? { type: 'activate_ability', instance_id: iid, ability_index: info.ability_index, mode: info.mode }
          : { type: 'tap_for_mana', instance_id: iid, ability_index: info.ability_index, option_index };
        castTargeting = {
          instanceId: iid, requirements, reqIndex: 0, targets: [], x: 0, send,
          excludePicked: true, isTapChoice: true, isExileChoice: !!action.exile_cost,
        };
        finishCastIfReady();
      });
    });

    root.querySelectorAll('[data-sacrifice-choice-start]').forEach((el) => {
      el.addEventListener('click', () => {
        const info = JSON.parse(el.dataset.sacrificeChoiceStart);
        const iid = Number(info.iid);
        const option_index = info.option_from_select
          ? Number(el.closest('.gf-mana-choice')?.querySelector('[data-mana-option]')?.value)
          : info.option_index;
        const action = (view?.legal_actions || []).find(
          (a) => a.type === info.type && a.instance_id === iid && a.ability_index === info.ability_index
            && sameActivationMode(a, info.mode),
        );
        if (!action || !action.sacrifice_cost) return;
        const { options, second_options: secondOptions, slots } = action.sacrifice_cost;
        // "Sacrifice a <type>" cost (RULE 602.1) — which permanent pays it
        // is the player's own choice, not an engine auto-pick; same
        // picker as `tap_cost` above. Paired costs gather a second distinct
        // pick, dispatched as `sacrifice_also_choice`. A cost with several slots ("a green creature, a white
        // creature, and a blue creature", "~ and 2 lands", RULE 701.17a: distinct objects) lists one option
        // list per pick in `slots`; the picks go back in that order as `tap_choices`.
        const requirements = slots
          ? slots.map((slotOptions) => ({ label: t('bd.sacrifice.permanent'), options: slotOptions, optional: false }))
          : [{ label: t('bd.sacrifice.permanent'), options, optional: false }];
        if (!slots && secondOptions) requirements.push({ label: t('bd.sacrifice.permanent'), options: secondOptions, optional: false });
        const send = info.type === 'activate_ability'
          ? { type: 'activate_ability', instance_id: iid, ability_index: info.ability_index, mode: info.mode }
          : { type: 'tap_for_mana', instance_id: iid, ability_index: info.ability_index, option_index };
        castTargeting = {
          instanceId: iid, requirements, reqIndex: 0, targets: [], x: 0, send,
          excludePicked: true, isSacrificeChoice: true, sacrificeSlots: Boolean(slots),
        };
        finishCastIfReady();
      });
    });

    root.querySelectorAll('[data-counter-choice-start]').forEach((el) => {
      el.addEventListener('click', () => {
        const info = JSON.parse(el.dataset.counterChoiceStart);
        const iid = Number(info.iid);
        castTargeting = {
          instanceId: iid, requirements: [], reqIndex: 0, targets: [], x: 0,
          send: { type: 'activate_ability', instance_id: iid, ability_index: info.ability_index, mode: info.mode },
        };
        finishCastIfReady();
      });
    });

    root.querySelectorAll('[data-discard-activate-start]').forEach((el) => {
      el.addEventListener('click', () => {
        const info = JSON.parse(el.dataset.discardActivateStart);
        const iid = Number(info.iid);
        const action = (view?.legal_actions || []).find(
          (a) => a.type === 'activate_ability' && a.instance_id === iid && a.ability_index === info.ability_index
            && sameActivationMode(a, info.mode),
        );
        if (!action || !action.discard_cost) return;
        const { count, options, matching_names, different_names } = action.discard_cost;
        // An activated ability's "Discard N cards" cost (RULE 602.2b): same one-pick-at-a-time modal as the cast
        // path's `discard_cost`, answered with `discard_choices`.
        const requirements = Array.from({ length: count }, () => ({
          label: t('bd.discard.card'), options, optional: false, matching_names, different_names,
        }));
        castTargeting = {
          instanceId: iid, requirements, reqIndex: 0, targets: [], x: 0,
          send: { type: 'activate_ability', instance_id: iid, ability_index: info.ability_index, mode: info.mode },
          excludePicked: true, isDiscardChoice: true,
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
          info.pay_additional, info.bargained, info.evoke, info.gift_opponent_id, info.surge, info.blitz, info.alt_cost, info.warp, info.splice_ids, info.free,
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
          replicate: readReplicate(iid, info.face, info.splice_ids),
          face: info.face, mode: info.mode, warp: action.warp, evoke: action.evoke, surge: action.surge, blitz: action.blitz,
          pay_additional: action.pay_additional,
          bargained: action.bargained, gift_opponent_id: action.gift_opponent_id, splice_ids: action.splice_ids, free: !!action.free, alt_cost: !!action.alt_cost,
        };
        castTargeting = {
          instanceId: iid, requirements, reqIndex: 0, targets: [], x: 0, send,
          excludePicked: true, isDiscardChoice: true,
        };
        finishCastIfReady();
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

  function readKicker(instanceId, face, spliceIds) {
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

  // ``mode`` disambiguates a modal spell's several `cast_spell` offers
  // (RULE 700.2 — same instance_id/type/face, one per mode or mode
  // combination via `_modal_cast_actions`) — without it this always
  // returned whichever mode `legal_actions` happened to list first,
  // regardless of which of the offered buttons was actually clicked.
  // Compared via JSON (not `===`) since a "choose N" mode is an array of
  // indices; absent on both sides (a non-modal spell/activated ability)
  // normalizes to the same `null` key either way.
  function findTargetableAction(iid, type, abilityIndex, face, mode, payAdditional, bargained, evoke, giftOpponentId, surge, blitz, altCost, warp, spliceIds, free) {
    const modeKey = JSON.stringify(mode ?? null);
    return (view?.legal_actions || []).find(
      (a) =>
        a.type === type &&
        a.instance_id === iid &&
        (type !== 'activate_ability' || a.ability_index === abilityIndex) &&
        (a.face || undefined) === (face || undefined) &&
        JSON.stringify(a.mode ?? null) === modeKey &&
        (altCost == null || Boolean(a.alt_cost) === Boolean(altCost)) &&
        Boolean(a.pay_additional) === Boolean(payAdditional) &&
        Boolean(a.bargained) === Boolean(bargained) &&
        Boolean(a.warp) === Boolean(warp) &&
        Boolean(a.evoke) === Boolean(evoke) &&
        Boolean(a.surge) === Boolean(surge) &&
        (a.blitz ?? null) === (blitz ?? null) &&
        // RULE 702.174a: the per-opponent "cast + promise a gift" offers are distinct entries.
        (a.gift_opponent_id || null) === (giftOpponentId || null) &&
        JSON.stringify(a.splice_ids || []) === JSON.stringify(spliceIds || []) &&
        (free == null || Boolean(a.free) === Boolean(free)),
    );
  }

  // VIS-14: with a target popup pushed aside, mark every legal candidate on
  // the board and make a click on it answer the popup. A permanent is its
  // card face (hand/battlefield/exile — or its stack entry in the rail), a
  // player is the title bar of their board (or the goldfish opponent strip).
  // A candidate with no element on the board (a graveyard list entry) simply
  // stays answerable from the popup.
  function wirePickTargets() {
    for (const pick of pickablesForBoard()) {
      let el = null;
      if (pick.instanceId != null) {
        const id = CSS.escape(String(pick.instanceId));
        el = root.querySelector(`[data-instance-id="${id}"] > .card`)
          || root.querySelector(`[data-stack-instance-id="${id}"] > .card`);
      } else if (pick.playerId != null) {
        const id = CSS.escape(String(pick.playerId));
        el = root.querySelector(`.gf-player-board[data-player-id="${id}"] .gf-player-board-head`)
          || root.querySelector(`.gf-opponent[data-player-id="${id}"]`);
      }
      if (!el) continue;
      el.classList.add('gf-pick-target');
      el.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        pick.activate();
      }, true);
    }
  }

  function finishCastIfReady() {
    if (!castTargeting) return;
    if (castTargeting.reqIndex < castTargeting.requirements.length) {
      persistCastTargetingDraft();
      render();
      return;
    }
    if (castTargeting.damageDivisions?.length && !castTargeting.allocatedDamage) {
      persistCastTargetingDraft();
      render();
      return;
    }
    const ct = castTargeting;
    const { send, targets, groups, x, isTapChoice, isSacrificeChoice, isDiscardChoice, isGraveyardExileChoice, isSacrificeCountChoice, isReturnChoice, isBlightChoice, isRevealChoice, isCounterChoice } = ct;
    let payload;
    if (isRevealChoice) {
      // PAR-247 (RULE 701.20a): the X cards shown for "Reveal X <colour> cards from your hand".
      payload = { ...send, hand_card_choices: targets.map((t) => t.instance_id) };
    } else if (isCounterChoice) {
      // PAR-247 (RULE 602.2b): the permanent and the counter kind a "remove a counter from ..." cost comes off.
      payload = { ...send, counter_choice: targets[0].instance_id, counter_kind: targets[0].counter_kind };
    } else if (isBlightChoice) {
      payload = { ...send, blight_choice: targets[0].instance_id };
    } else if (isReturnChoice) {
      payload = { ...send, return_choices: targets.map((t) => t.instance_id) };
    } else if (isSacrificeCountChoice) {
      payload = { ...send, sacrifice_choices: targets.map((t) => t.instance_id) };
    } else if (isGraveyardExileChoice) {
      payload = { ...send, graveyard_exile_choices: targets.map((t) => t.instance_id) };
    } else if (isTapChoice) {
      payload = { ...send, tap_choices: targets.map((t) => t.instance_id) };
    } else if (isSacrificeChoice && ct.sacrificeSlots) {
      payload = { ...send, tap_choices: targets.map((t) => t.instance_id) };
    } else if (isSacrificeChoice) {
      payload = { ...send, sacrifice_choice: targets[0].instance_id,
        ...(targets[1] ? { sacrifice_also_choice: targets[1].instance_id } : {}),
      };
    } else if (isDiscardChoice) {
      payload = { ...send, discard_choices: targets.map((t) => t.instance_id) };
    } else {
      payload = { ...send, targets, x, ...((groups || []).length > 1 ? { target_groups: groups } : {}),
        ...(ct.allocatedDamage ? { damage_divisions: ct.allocatedDamage } : {}) };
    }
    let action = findTargetableAction(ct.instanceId, send.type, send.ability_index,
      send.face, send.mode, send.pay_additional, send.bargained, send.evoke,
      send.gift_opponent_id, send.surge, send.blitz, send.alt_cost, send.warp, send.splice_ids, send.free);
    if (action) action = selectedKickerAction(action, send.kicked);
    if (!payload.tap_choices && action?.power_tap_cost) {
      const cost = action.power_tap_cost;
      castTargeting = { instanceId: ct.instanceId, send: payload, x,
        requirements: Array.from({ length: cost.options.length + 1 }, () => ({
          label: t('bd.cast.tapPowerCreatures'), options: cost.options, optional: true,
        })), reqIndex: 0, targets: [], excludePicked: true, isTapChoice: true,
        isPowerTapChoice: true, powerRequired: cost.power_required, powerTapOptions: cost.options };
      finishCastIfReady();
      return;
    }
    if (!payload.tap_choices && action?.tap_cost) {
      const { options } = action.tap_cost;
      const count = action.tap_cost.count === 'x' ? x : action.tap_cost.count;
      castTargeting = { instanceId: ct.instanceId, send: payload, x,
        requirements: Array.from({ length: count }, () => ({
          label: action.tap_cost.untap ? t('bd.untap.permanent') : 'zu tappende bleibende Karte', options, optional: false,
          shared_creature_type: action.tap_cost.shared_creature_type,
        })),
        reqIndex: 0, targets: [], excludePicked: true, isTapChoice: true,
      };
      finishCastIfReady();
      return;
    }
    if (!payload.return_choices && action?.return_cost) {
      const { count, options } = action.return_cost;
      castTargeting = { instanceId: ct.instanceId, send: payload, x,
        requirements: Array.from({ length: count }, () => ({
          label: t('bd.return.costCard'), options, optional: false,
        })),
        reqIndex: 0, targets: [], excludePicked: true, isReturnChoice: true,
      };
      persistCastTargetingDraft();
      render();
      return;
    }
    // PAR-247: "Reveal X <colour> cards from your hand" (the Martyrs) -- X was announced above, now the cards.
    if (send.type === 'activate_ability' && !isRevealChoice && action?.reveal_cost && !payload.hand_card_choices) {
      const { options, shared_color } = action.reveal_cost;
      const count = Math.min(action.reveal_cost.count === 'x' ? (payload.x ?? x ?? 0) : action.reveal_cost.count, options.length);
      if (count > 0) {
        castTargeting = { instanceId: ct.instanceId, send: payload, x,
          requirements: Array.from({ length: count }, () => ({ label: t('bd.reveal.card'), options, optional: false, shared_color })),
          reqIndex: 0, targets: [], excludePicked: true, isRevealChoice: true };
        persistCastTargetingDraft();
        render();
        return;
      }
      payload.hand_card_choices = [];
    }
    // PAR-247: "Remove a counter from a permanent you control" -- the player picks the holder and the counter kind.
    if (send.type === 'activate_ability' && !isCounterChoice && action?.counter_cost && payload.counter_choice == null) {
      castTargeting = { instanceId: ct.instanceId, send: payload, x,
        requirements: [{ label: t('bd.counter.holder'), options: action.counter_cost.options, optional: false }],
        reqIndex: 0, targets: [], excludePicked: true, isCounterChoice: true };
      persistCastTargetingDraft();
      render();
      return;
    }
    // RULE 602.2b: an activated ability that targets *and* sacrifices / discards asks for those payments after its
    // targets, so the engine never auto-picks the permanents or cards (PAR-232: Doom Cannon, Sanctum Spirit, ...).
    if (send.type === 'activate_ability' && !isSacrificeChoice && action?.sacrifice_cost
        && payload.sacrifice_choice == null && !payload.tap_choices) {
      const { options, second_options: secondOptions, slots } = action.sacrifice_cost;
      const requirements = slots
        ? slots.map((slotOptions) => ({ label: t('bd.sacrifice.permanent'), options: slotOptions, optional: false }))
        : [{ label: t('bd.sacrifice.permanent'), options, optional: false }];
      if (!slots && secondOptions) requirements.push({ label: t('bd.sacrifice.permanent'), options: secondOptions, optional: false });
      castTargeting = { instanceId: ct.instanceId, send: payload, x, requirements, reqIndex: 0, targets: [],
        excludePicked: true, isSacrificeChoice: true, sacrificeSlots: Boolean(slots) };
      persistCastTargetingDraft();
      render();
      return;
    }
    if (send.type === 'activate_ability' && !isDiscardChoice && action?.discard_cost && !payload.discard_choices) {
      const { count, matching_names, different_names } = action.discard_cost;
      const options = action.discard_cost.options.filter((option) => !action.discard_cost.mana_value_equals_x || option.mana_value === (payload.x ?? x ?? 0));
      castTargeting = { instanceId: ct.instanceId, send: payload, x,
        requirements: Array.from({ length: count }, () => ({ label: t('bd.discard.card'), options, optional: false, matching_names, different_names })),
        reqIndex: 0, targets: [], excludePicked: true, isDiscardChoice: true };
      persistCastTargetingDraft();
      render();
      return;
    }
    // RULE 701.68: which creature pays a "Blight N" cost is the player's choice (one candidate needs no prompt).
    if (payload.blight_choice == null && action?.blight_cost?.options?.length > 1) {
      castTargeting = { instanceId: ct.instanceId, send: payload, x,
        requirements: [{ label: t('bd.blight.costCreature'), options: action.blight_cost.options, optional: false }],
        reqIndex: 0, targets: [], excludePicked: true, isBlightChoice: true,
      };
      persistCastTargetingDraft();
      render();
      return;
    }
    if (!payload.sacrifice_choices && action?.sacrifice_count_cost) {
      const { count, count_max: maximum, options, verb } = action.sacrifice_count_cost;
      const minimum = count === 'x' ? (payload.x || 0) : count;
      const total = maximum ?? minimum;
      if (total > 0) {
        castTargeting = { instanceId: ct.instanceId, send: payload, x,
          requirements: Array.from({ length: total }, (_, index) => ({
            label: t(verb === 'return' ? 'bd.return.costCard' : 'bd.sacrifice.permanent'), options, optional: index >= minimum,
          })),
          reqIndex: 0, targets: [], excludePicked: true, isSacrificeCountChoice: true,
        };
        persistCastTargetingDraft();
        render();
        return;
      }
      payload.sacrifice_choices = [];
    }
    if (!isGraveyardExileChoice && action?.graveyard_exile_cost) {
      const { count, options } = action.graveyard_exile_cost;
      const eligible = action.graveyard_exile_cost.mana_value_equals_x
        ? options.filter(option => option.mana_value === (payload.x || 0)) : options;
      castTargeting = { instanceId: ct.instanceId, send: payload, x,
        requirements: Array.from({ length: count }, () => ({
          label: t('bd.exile.graveyardCostCard'), options: eligible, optional: false,
        })),
        reqIndex: 0, targets: [], excludePicked: true, isGraveyardExileChoice: true,
      };
      persistCastTargetingDraft();
      render();
      return;
    }
    castTargeting = null;
    act(payload);
    persistCastTargetingDraft();
  }

  // --- Rendering helpers ------------------------------------------------

  // The battlefield, laid out in rows by card type (creatures / artifacts &
  // enchantments / lands). Attachments (Auras, Equipment — RULE 301/303) are
  // pulled out of the flow and drawn inside a dashed group box around the
  // permanent they're attached to, rather than as loose cards.
  function battlefieldHtml(objs, controllerId, byInstance = {}, pending = null) {
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
    // Attachments can be controlled by a different player than their host (RULE 303.4e).
    // Build the group from the whole battlefield, then place it on the host's board.
    const top = objs.filter((o) => !attachedIds.has(o.instance_id) && o.controller_id === controllerId);
    if (!top.length) return `<p class="empty-state">${t('bd.bf.none')}</p>`;

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
      const tile = objCard(o, imageCache, pending ? [] : byInstance[o.instance_id] || []);
      const card = o.controller_id !== controllerId
        ? `<div class="gf-foreign-attachment">${tile}<small>${escapeHtml(t('bd.target.controllerTitle', { name: playerName(o.controller_id) }))}</small></div>`
        : tile;
      const nested = attachments.get(o.instance_id);
      if (!nested || !nested.length) return card;
      return card + nested.map(renderAttached).join('');
    };

    const renderObj = (o) => {
      const actions = pending ? [] : byInstance[o.instance_id] || [];
      const host = objCard(o, imageCache, actions, true);
      const atts = attachments.get(o.instance_id);
      if (!atts || !atts.length) return host;
      const attached = atts.map(renderAttached).join('');
      return `<div class="gf-attach-group" title="${escapeAttr(t('bd.bf.attachTitle'))}">${host}${attached}</div>`;
    };

    const rowHtml = (rowKey, label, list) =>
      `<div class="gf-bf-row">
        <span class="gf-bf-row-label">${label} (${list.length})</span>
        ${list.length ? `<div class="card-grid" data-order-zone="${escapeAttr(`bf:${controllerId}:${rowKey}`)}">${orderedByLocal(`bf:${controllerId}:${rowKey}`, list).map(renderObj).join('')}</div>` : '<p class="empty-state">–</p>'}
      </div>`;

    const rows = threeRows
      ? [
          rowHtml('creatures', t('bd.bf.rowCreatures'), creatures),
          rowHtml('other', t('bd.bf.rowArtEnch'), other),
          rowHtml('lands', t('bd.bf.rowLands'), lands),
        ]
      : [
          rowHtml('creatures', t('bd.bf.rowCreatures'), creatures),
          rowHtml('mixed', t('bd.bf.rowLandsPermanents'), other.concat(lands)),
        ];
    return `<div class="gf-bf-rows">${rows.join('')}</div>`;
  }

  function blindSideboardHtml(player, state) {
    const slots = (view.legal_actions || []).filter(a => a.blind_sideboard && player.id === view.acting_as);
    if (!slots.length) return '';
    // RULE 724.4: choices use only public objects, never hidden cast metadata.
    const targets = [
      ...(state.players || []).map(p => ({value: {player_id: p.id}, label: p.name})),
      ...(state.battlefield || []).map(o => ({value: {instance_id: o.instance_id}, label: o.name})),
      ...(state.stack || []).map(o => ({value: o.object ? {instance_id: o.object.instance_id} : {stack_id: o.stack_id}, label: o.object?.name || o.description || 'Stack'})),
    ];
    return `<details class="gf-blind-sideboard"><summary>${t('bd.sideboard.blind')}</summary>
      <label>${t('bd.sideboard.card')} <select data-blind-slot>${slots.map((a, i) => `<option value="${a.instance_id}">${i + 1}</option>`).join('')}</select></label>
      <label>X <input data-blind-x type="number" min="0" value="0"></label>
      <label>${t('bd.sideboard.face')} <select data-blind-face><option value="front">1</option><option value="back">2</option></select></label>
      <label>${t('bd.sideboard.mode')} <input data-blind-mode type="number" min="1" placeholder="–"></label>
      <label>${t('bd.sideboard.targets')} <select data-blind-targets multiple>${targets.map(o => `<option value='${escapeAttr(JSON.stringify(o.value))}'>${escapeHtml(o.label)}</option>`).join('')}</select></label>
      <button type="button" data-blind-cast>${t('bd.sideboard.cast')}</button></details>`;
  }

  function objGrid(objs, empty, byInstance = {}, pending = null) {
    if (!objs.length) return `<p class="empty-state">${empty}</p>`;
    const imageCache = getState().imageCache;
    return `<div class="card-grid">${objs
      .map((o) => objCard(o, imageCache, pending ? [] : byInstance[o.instance_id] || []))
      .join('')}</div>`;
  }

  // The source card's art as a mini card; an ability overlays only its own
  // description (never the whole Oracle text: a source can have several
  // unrelated abilities). Without art, a text box shows the same content.
  function stackItemHtml(item, index, total, opts = {}) {
    const isAbility = item.kind === 'ability';
    const visual = item.object || item.source;
    const badge = stackKindBadge(item);
    const actionText = isAbility
      ? (item.description && item.description !== visual?.name ? item.description : badge.label)
      : item.kind === 'spell' ? 'Cast' : (item.description || item.kind);
    const displayName = visual?.name || '';
    const imageUrl = visual ? resolveImageUrl(visual, getState().imageCache) : null;
    const isTop = !opts.ghost && index === total - 1;
    // `opts.ghost` = a just-resolved entry lingering for a moment: no LIFO
    // position, just an "aufgelöst" caption.
    const orderText = opts.ghost
      ? t('bd.rail.stackResolved')
      : total > 1
        ? (isTop ? t('bd.stack.topResolves') : `#${total - index}`)
        : '';
    const order = orderText ? `<span class="gf-stack-order">${escapeHtml(orderText)}</span>` : '';
    return `
      <div data-stack-id="${escapeAttr(item.stack_id)}" class="gf-card-slot gf-stack-item${isTop ? ' is-top' : ''}${opts.ghost ? ' gf-rail-stack-ghost' : ''}"${!opts.ghost && visual?.instance_id != null ? ` data-stack-instance-id="${escapeAttr(visual.instance_id)}"` : ''}>
        <span class="gf-stack-badge gf-stack-badge--${badge.cls}">${badge.icon} ${escapeHtml(badge.label)}</span>
        ${imageUrl
          ? `<div class="card has-image gf-stack-art"${displayName ? ` data-hover-card="${escapeAttr(displayName)}" title="${escapeAttr(displayName)}"` : ''}>
          <img src="${imageUrl}" alt="${escapeAttr(displayName)}" loading="lazy" />
          ${isAbility ? `<div class="gf-stack-ability-overlay">${renderOracleText(actionText)}</div>` : ''}
        </div>`
          : `<div class="card gf-stack-action"${displayName ? ` data-hover-card="${escapeAttr(displayName)}"` : ''}>
          ${displayName ? `<strong class="gf-stack-source-name">${escapeHtml(displayName)}</strong>` : ''}
          <span class="gf-stack-action-text">${renderOracleText(actionText)}</span>
        </div>`}
        ${order}
      </div>`;
  }

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
  // its real transformed state (RULE 712.6), inverted by a client-only
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

  function objCard(o, imageCache, cardActions, reorderable = false) {
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
    // RULE 710: a flipped flip-card permanent is the same card turned upside down (its alternative half is
    // printed rotated 180° on the one shared image).
    if (o.flipped) classes.push('flipped');
    if (isSummoningSick) classes.push('summoning-sick');
    if (o.attacking || attackDraft.has(o.instance_id)) classes.push('attacking');
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
    // RULE 117.1a / 307.1: the server's legal actions include timing and
    // priority checks; mana potential alone must never light up a card.
    const playableNow = (cardActions || []).some(a =>
      (a.type === 'cast_spell' || a.type === 'play_land') && !selectedKickerAction(a).locked);
    if (playableNow) {
      classes.push('castable-highlight');
    }
    const remainingToughness = o.toughness - (o.damage_marked || 0);
    const pt = o.power != null && o.toughness != null ? ` (${o.power}/${remainingToughness})` : '';
    const hasBasePt = o.base_power != null && o.base_toughness != null;
    const ptChanged = o.power != null && o.toughness != null && hasBasePt
      && (o.power !== o.base_power || remainingToughness !== o.base_toughness);
    const compactPt = o.zone === 'battlefield' && o.is_creature
      && o.power != null && o.toughness != null
      ? `<span class="gf-compact-pt${ptChanged ? ' is-changed' : ''}" title="${escapeAttr(`${o.power}/${remainingToughness}`)}">${o.power}/${remainingToughness}</span>`
      : '';
    const attackActions = (cardActions || []).filter(a => a.type === 'attack');
    const menuActions = cardActions || [];
    const menuId = `gf-card-menu-${o.instance_id}-${++cardMenuSerial}`;
    const attack = { draft: attackDraft, menuOpen: attackMenuOpen, busy };
    const buttons = cardActionButtons(attackActions, attack);
    const menu = `<div id="${menuId}" popover="manual" class="gf-card-menu" aria-label="${escapeAttr(o.name)}">${menuActions.map(a => `<div class="gf-menu-option">${cardActionButtons([a], attack)}${a.type === 'cast_spell' ? `<span class="gf-menu-cost">${renderOracleText(a.effective_cost || a.cost_label || a.base_cost || o.mana_cost || '{0}')}</span>` : ''}</div>`).join('') || unavailableCardActionsHtml(o)}</div>`;
    const attackBadge = attackDraft.has(o.instance_id)
      ? `<span class="gf-attacking-badge">⚔️ ${escapeHtml(t('bd.attack.selected'))}${attackDraft.get(o.instance_id).defender_label ? ` → ${escapeHtml(attackDraft.get(o.instance_id).defender_label)}` : ''}</span>`
      : o.attacking
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
    // RULE 715: a Saga's chapter progress, mirroring the loyalty badge above
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
    // RULE 716.3d: an Adventure creature exiled by its own spell half,
    // castable from here — flags it distinctly from an inert exiled card.
    const adventureBadge = o.adventure_castable
      ? `<span class="gf-adventure-badge" title="${escapeAttr(t('bd.badge.adventureTitle'))}">${t('bd.badge.adventure')}</span>`
      : '';
    // RULE 723.3a: this permanent is prepared — its exiled prepare-spell
    // copy is castable (badged on that copy's own tile via `prepared_copy`
    // below, since that's a property of the copy, not of this permanent).
    const preparedBadge = o.prepared
      ? `<span class="gf-prepared-badge" title="${escapeAttr(t('bd.badge.preparedTitle'))}">${t('bd.badge.prepared')}</span>`
      : '';
    // RULE 723.3c: this *is* that exiled prepare-spell copy.
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
    // RULE 709.5c: a Room shows each of its two doors, unlocked or locked (a locked half has no name or rules text
    // of its own until it is unlocked).
    const roomBadge = o.room_doors
      ? `<span class="gf-room-badge" title="${escapeAttr(t('bd.badge.roomTitle'))}">${o.room_doors.map((d) => `<span class="gf-room-door${d.unlocked ? ' gf-room-door--open' : ''}" title="${escapeAttr(t(d.unlocked ? 'bd.badge.doorUnlocked' : 'bd.badge.doorLocked', { door: d.name }))}">${d.unlocked ? '🔓' : '🔒'}</span>`).join('')}</span>`
      : '';
    const effectsSummary = effectSummaryHtml(o);
    // A double-faced permanent (transform/modal DFC) gets a "🔄 peek other
    // face" button — purely a client-side preview (`flippedForView`), not
    // an actual transform (RULE 712.6 stays a real game action, offered
    // instead among `buttons` when the card's own ability allows it).
    const flipButton = o.has_back_face
      ? `<button type="button" class="gf-card-flip" data-flip-toggle="${o.instance_id}" title="Andere Seite ansehen" aria-label="Andere Seite ansehen">🔄</button>`
      : '';
    const draggable = reorderable || (cardActions && cardActions.some(isPlayableCardAction));
    const dragAttrs = draggable ? ` draggable="true" data-draggable-card="true"` : '';
    return `
      <div class="gf-card-slot" data-instance-id="${escapeAttr(o.instance_id)}"${menu ? ` data-card-menu="${menuId}"` : ''}>
        <div class="${classes.join(' ')}"${dragAttrs} data-hover-card="${escapeHtml(o.name)}" title="${escapeHtml(o.name)}${pt}${o.tapped ? escapeAttr(t('bd.tile.tapped')) : ''}"><span class="gf-card-art">${inner}${summoningSickBadge}${targetOverlay}</span>${flipButton}${attackBadge}${loyaltyBadge}${battleBadge}${counterBadge}${keywordBadge}${compactPt}${adventureBadge}${preparedBadge}${preparedCopyBadge}${faceDownBadge}${roomBadge}${effectsSummary}</div>
        ${buttons}${menu}
      </div>`;
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

  function damageDivisionModalHtml() {
    const ct = castTargeting;
    const rows = ct.damageDivisions.map((division) => {
      const index = division.requirement_index;
      const requirement = ct.divisionRequirements?.[index];
      const targets = ct.groups?.[index] || [];
      const fields = targets.map((target, row) => {
        const option = requirement?.options?.find((candidate) => target.player_id != null
          ? candidate.player_id === target.player_id : candidate.instance_id === target.instance_id);
        return `<label>${escapeHtml(option?.name || `Ziel ${row + 1}`)}
          <input type="number" min="${escapeAttr(division.min_each)}" max="${escapeAttr(division.total)}" step="1" value="${escapeAttr(ct.damageDraft?.[index]?.[row] ?? division.min_each)}" data-damage-requirement="${escapeAttr(index)}" />
        </label>`;
      }).join('');
      return `<fieldset><legend>${escapeHtml(requirement?.label || 'Schaden verteilen')} — insgesamt ${escapeHtml(division.total)}</legend>${fields}</fieldset>`;
    }).join('');
    return `<div class="gf-modal-overlay"><div class="gf-modal gf-target-modal" role="dialog" aria-modal="true">
      <h4>Schaden verteilen</h4>${rows}<p data-damage-error role="alert"></p>
      <div class="gf-modal-foot"><button type="button" data-damage-confirm>Bestätigen</button>
        <button type="button" data-cast-target-cancel="${escapeAttr(ct.instanceId)}">✕ Abbrechen</button></div>
    </div></div>`;
  }

  function castTargetModalHtml() {
    if (!castTargeting) return '';
    if (castTargeting.reqIndex >= castTargeting.requirements.length && castTargeting.damageDivisions?.length) return damageDivisionModalHtml();
    const iid = castTargeting.instanceId;
    const total = castTargeting.requirements.length;
    const idx = castTargeting.reqIndex;
    const req = castTargeting.requirements[idx] || {};
    const options = castTargetOptions();
    // A cost *choice* (RULE 602.1: tap N / sacrifice / discard for a cost),
    // not a RULE 115 target — different heading and glyph from "Ziel wählen".
    const isDiscardChoice = castTargeting.isDiscardChoice;
    const isCostChoice = castTargeting.isTapChoice || castTargeting.isSacrificeChoice || isDiscardChoice || castTargeting.isGraveyardExileChoice || castTargeting.isSacrificeCountChoice || castTargeting.isReturnChoice || castTargeting.isBlightChoice || castTargeting.isRevealChoice || castTargeting.isCounterChoice;
    const modalGlyph = castTargeting.isCounterChoice ? '🔢' : castTargeting.isRevealChoice ? '👁️' : castTargeting.isBlightChoice ? '🥀' : castTargeting.isReturnChoice ? '↩️' : (castTargeting.isGraveyardExileChoice || castTargeting.isExileChoice) ? '🌀' : isDiscardChoice ? '🗑️' : (castTargeting.isTapChoice ? '⟳' : ((castTargeting.isSacrificeChoice || castTargeting.isSacrificeCountChoice) ? '💀' : '🎯'));
    const buttons = options.map((o) => {
      const payload = JSON.stringify({
        instance_id: iid, target: targetOptionPayload(o), controller_id: o.controller_id ?? null,
      });
      const hover = o.instance_id != null ? ` data-hover-card="${escapeHtml(o.name || '')}"` : '';
      // VIS-13: who controls this candidate, so two same-named permanents
      // on different boards can be told apart.
      const name = castTargeting.isPowerTapChoice ? `${o.name} (${o.power})` : o.name;
      return `<button type="button"${hover} data-cast-target-pick='${escapeAttr(payload)}'>${modalGlyph} ${escapeHtml(name)}${targetControllerChipHtml(o)}</button>`;
    });
    if (req.optional && (!castTargeting.isPowerTapChoice || powerTapTotal(castTargeting) >= castTargeting.powerRequired)) {
      const skip = JSON.stringify({ instance_id: iid, target: null });
      buttons.push(`<button type="button" class="gf-decline" data-cast-target-pick='${escapeAttr(skip)}'>${t(castTargeting.isSacrificeCountChoice || castTargeting.isPowerTapChoice ? 'bd.cast.finishCostChoice' : 'bd.cast.noTarget')}</button>`);
    }
    const heading = isCostChoice ? t('bd.cast.payCosts') : t('bd.cast.chooseTarget');
    const progress = castTargeting.isPowerTapChoice
      ? t('bd.cast.tapPowerProgress', { power: powerTapTotal(castTargeting), required: castTargeting.powerRequired })
      : total > 1 ? t('bd.cast.progress', { i: idx + 1, total }) : (isCostChoice ? t('bd.cast.select') : t('bd.cast.chooseTarget'));
    // VIS-14: only a real target round can be answered by clicking the
    // board; a cost choice (tap/sacrifice/discard) keeps the popup-only flow.
    const asideOffered = !isCostChoice;
    const aside = asideOffered && castTargetAside;
    const asideButton = asideOffered
      ? `<button type="button" class="gf-modal-aside" data-cast-target-aside title="${escapeAttr(t('bd.cast.asideTitle'))}">${aside ? t('bd.choice.asideShow') : t('bd.choice.asidePush')}</button>`
      : '';
    return `
      <div class="gf-modal-overlay${aside ? ' aside' : ''}">
        <div class="gf-modal gf-target-modal" role="dialog" aria-modal="true">
          <div class="gf-modal-head">
            <span class="gf-modal-icon">${modalGlyph}</span>
            <div>
              <h4>${heading}: ${escapeHtml(req.label || '')}</h4>
              <p class="gf-modal-who">${escapeHtml(progress)}</p>
              ${aside ? `<p class="gf-modal-source">${escapeHtml(t('bd.cast.asideHint'))}</p>` : ''}
            </div>
            ${asideButton}
          </div>
          <div class="gf-choice-options">${buttons.join('')}</div>
          <div class="gf-modal-foot">
            <button type="button" class="gf-decline" data-cast-target-cancel="${iid}">✕ Abbrechen</button>
          </div>
        </div>
      </div>
    `;
  }

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
