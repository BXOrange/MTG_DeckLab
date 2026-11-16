import { getStopsPref, setStopsPref } from '../settings.js';

const OWN_TURN_TIMER_STEPS = new Set(['upkeep', 'draw', 'end']);
const STOP_STEPS = [
  'upkeep', 'draw', 'main1', 'begin_combat', 'declare_attackers',
  'declare_blockers', 'combat_damage', 'end_combat', 'main2', 'end',
];
const ALWAYS_STOP_OWN_TURN = ['main1', 'main2'];

export function createPriorityController({
  getView,
  getRoot,
  getBusy,
  getSessionId,
  getAttackDraftSize,
  act,
  staticEffectsButtonHtml,
  t,
  escapeHtml,
  escapeAttr,
  stepLabels,
}) {
  let autoPassSeconds = 0;
  let autoPassTimer = null;
  let autoPassRemaining = 0;
  let autoPassCancelled = false;
  let autoPassWindowKey = null;
  let skipAttemptedForKey = null;
  let stopsSynced = false;
  let stopsPanelOpen = false;

  function interactivePriority() {
    const view = getView();
    return !!view?.priority?.interactive && !view.observer;
  }

  function actingSeat() {
    const view = getView();
    return view?.acting_as || view?.perspective || null;
  }

  function hasPriority() {
    const view = getView();
    if (!view?.priority || view.state?.pending_choice || view.state?.waiting_on_choice) return false;
    const pid = view.priority.player_id;
    return (
      (!!actingSeat() && pid === actingSeat()) ||
      (!!view.perspective && pid === view.perspective)
    );
  }

  function hasMeaningfulAction() {
    return (getView()?.legal_actions || []).some((action) => action.type !== 'pass_priority');
  }

  function skipEmptyArmed() {
    const view = getView();
    if (!interactivePriority() || !hasPriority() || !view) return false;
    const state = view.state;
    if (state.game_over || state.pending_choice || getBusy()) return false;
    return !hasMeaningfulAction();
  }

  function reactTimerSuppressedHere() {
    const view = getView();
    const mine = actingSeat();
    const state = view?.state;
    if (!mine || !state || state.active_player_id !== mine) return false;
    if (state.stack && state.stack.length > 0) return false;
    return !OWN_TURN_TIMER_STEPS.has(state.current_step);
  }

  function autoPassArmed() {
    const view = getView();
    if (autoPassCancelled || autoPassSeconds <= 0) return false;
    if (!interactivePriority() || !hasPriority() || !view) return false;
    const state = view.state;
    if (state.game_over || state.pending_choice || getBusy()) return false;
    if (reactTimerSuppressedHere()) return false;
    return true;
  }

  function myYield() {
    const seat = actingSeat();
    return (seat && getView()?.priority?.yields?.[seat]) || null;
  }

  function priorityWindowKey() {
    const view = getView();
    const state = view?.state;
    if (!state) return null;
    return [
      state.internal_turn.number,
      state.current_step,
      view.priority?.player_id,
      (view.priority?.passed || []).join(','),
      state.stack.length,
    ].join('|');
  }

  function stopAutoPass() {
    if (autoPassTimer !== null) {
      clearInterval(autoPassTimer);
      autoPassTimer = null;
    }
  }

  function serverTimerSeconds() {
    const n = Number(getView()?.priority?.timer_seconds);
    return Number.isFinite(n) && n > 0 ? Math.round(n) : 0;
  }

  function updateTimerSeconds() {
    autoPassSeconds = serverTimerSeconds();
    return autoPassSeconds;
  }

  function syncStopsPref() {
    const view = getView();
    if (stopsSynced || getBusy() || !interactivePriority() || !view?.perspective) return;
    stopsSynced = true;
    if (view.priority.stops?.[view.perspective]) return;
    const pref = getStopsPref();
    if (pref) act({ type: 'set_stops', own: pref.own, opponent: pref.opponent });
  }

  function syncAutoPass() {
    syncStopsPref();
    updateTimerSeconds();
    const windowKey = priorityWindowKey();
    if (skipEmptyArmed() && windowKey !== skipAttemptedForKey) {
      skipAttemptedForKey = windowKey;
      stopAutoPass();
      act({ type: 'pass_priority' });
      return;
    }
    if (windowKey !== autoPassWindowKey) {
      autoPassWindowKey = windowKey;
      autoPassCancelled = false;
      stopAutoPass();
    }
    if (!autoPassArmed()) {
      stopAutoPass();
      return;
    }
    if (autoPassTimer !== null) return;
    autoPassRemaining = autoPassSeconds;
    paintCountdown();
    autoPassTimer = setInterval(() => {
      autoPassRemaining -= 1;
      paintCountdown();
      if (autoPassRemaining > 0) return;
      stopAutoPass();
      if (autoPassArmed()) act({ type: 'pass_priority' });
    }, 1000);
  }

  function paintCountdown() {
    const root = getRoot();
    const remaining = Math.max(0, autoPassRemaining);
    root?.querySelectorAll('[data-timer-count]').forEach((el) => {
      el.textContent = String(remaining);
    });
    const frac = autoPassSeconds > 0 ? remaining / autoPassSeconds : 0;
    root?.querySelectorAll('[data-timer-bar]').forEach((el) => {
      el.style.setProperty('--gf-timer-frac', String(frac));
    });
  }

  function cancelAutoPassForThisWindow() {
    if (autoPassTimer === null && !autoPassCancelled) return;
    autoPassCancelled = true;
    stopAutoPass();
    getRoot()?.querySelector('.gf-rail-timer')?.classList.add('gf-timer-off');
  }

  function priorityControlsHtml(extra) {
    return `
      <div class="gf-controls gf-rail-controls gf-priority-controls">
        ${staticEffectsButtonHtml()}
        ${extra}
      </div>`;
  }

  function passButtonHtml(disabled, extraClass = '') {
    const view = getView();
    const next = view.priority?.next_step;
    const toNext = next ? t(`bd.ctrl.passTo.${next}`) : '';
    const attackDraftSize = getAttackDraftSize();
    const label = attackDraftSize && !view.state.stack.length
      ? t('bd.attack.confirm', { count: attackDraftSize })
      : view.state.stack.length > 0
      ? t('bd.ctrl.passResolve')
      : (toNext && toNext !== `bd.ctrl.passTo.${next}` ? toNext : t('bd.ctrl.pass'));
    return `<button type="button" class="primary${extraClass}" data-pass-priority title="${escapeAttr(t('bd.ctrl.passTitle'))}" ${disabled ? 'disabled' : ''}>${label}</button>`;
  }

  function yieldButtonsHtml(disabled, extraClass = '') {
    const view = getView();
    const armed = myYield();
    if (armed) {
      const label = armed === 'end_step' ? t('bd.ctrl.yieldEndStepActive') : t('bd.ctrl.yieldTurnActive');
      return `<button type="button" class="gf-yield gf-yield-active${extraClass}" data-yield="clear" title="${escapeAttr(t('bd.ctrl.yieldCancelTitle'))}" ${disabled ? 'disabled' : ''}>${label}</button>`;
    }
    const state = view.state;
    if (!view.perspective) return '';
    if (state.active_player_id !== actingSeat()) {
      return `<button type="button" class="gf-yield${extraClass}" data-yield="turn" title="${escapeAttr(t('bd.ctrl.passTurnTitle'))}" ${disabled ? 'disabled' : ''}>${t('bd.ctrl.passTurn')}</button>`;
    }
    if (state.current_step === 'end') return '';
    return `<button type="button" class="gf-yield${extraClass}" data-yield="end_step" title="${escapeAttr(t('bd.ctrl.skipToEndTitle'))}" ${disabled ? 'disabled' : ''}>${t('bd.ctrl.skipToEnd')}</button>`;
  }

  function yieldBadgeHtml(playerId) {
    const mode = getView().priority?.yields?.[playerId];
    if (!mode) return '';
    const label = mode === 'end_step' ? t('bd.badge.yieldEndStep') : t('bd.badge.yieldTurn');
    return `<span class="gf-yield-badge">${escapeHtml(label)}</span>`;
  }

  function priorityBadgeHtml(holdsPriority, isMe, playerName) {
    if (!holdsPriority) return '';
    const title = isMe ? t('bd.priority.mine') : t('bd.priority.holder', { name: playerName });
    return `<span class="gf-priority-badge${isMe ? ' gf-priority-mine' : ''}" title="${escapeAttr(title)}">⚡</span>`;
  }

  function railTimerHtml() {
    const view = getView();
    if (!interactivePriority() || !hasPriority() || autoPassSeconds <= 0) return '';
    const state = view.state;
    if (state.game_over || state.pending_choice) return '';
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

  function currentStops() {
    const view = getView();
    const seat = view?.perspective;
    return view?.priority?.stops?.[seat] || { own: [...STOP_STEPS], opponent: [...STOP_STEPS] };
  }

  function railStopsHtml() {
    const view = getView();
    if (!interactivePriority() || !view?.perspective || view.state.game_over) return '';
    const stops = currentStops();
    const rows = STOP_STEPS.map((step) => {
      const own = stops.own.includes(step);
      const opp = stops.opponent.includes(step);
      const locked = ALWAYS_STOP_OWN_TURN.includes(step);
      return `<tr>
        <td>${escapeHtml(stepLabels[step] || step)}</td>
        <td><input type="checkbox" data-stop="own" data-step="${step}" ${own ? 'checked' : ''} ${locked || getBusy() ? 'disabled' : ''}></td>
        <td><input type="checkbox" data-stop="opponent" data-step="${step}" ${opp ? 'checked' : ''} ${getBusy() ? 'disabled' : ''}></td>
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
    const panel = getRoot()?.querySelector('[data-stops-panel]');
    if (!panel) return;
    panel.addEventListener('toggle', () => { stopsPanelOpen = panel.open; });
    panel.querySelectorAll('input[data-stop]').forEach((box) => {
      box.addEventListener('change', () => {
        const next = { own: [], opponent: [] };
        panel.querySelectorAll('input[data-stop]:checked').forEach((checkbox) => {
          next[checkbox.dataset.stop].push(checkbox.dataset.step);
        });
        setStopsPref(next);
        act({ type: 'set_stops', own: next.own, opponent: next.opponent });
      });
    });
  }

  function onShortcutKey(event) {
    const view = getView();
    const root = getRoot();
    if (!getSessionId() || !view || !root?.isConnected || root.offsetParent === null) return;
    if (!interactivePriority() || getBusy() || view.state.game_over || view.state.pending_choice) return;
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
    if (!mode || myYield() || (mode === 'turn') === ownTurn) return;
    if (mode === 'end_step' && view.state.current_step === 'end') return;
    event.preventDefault();
    act({ type: 'set_yield', mode });
  }
  document.addEventListener('keydown', onShortcutKey);

  return {
    actingSeat,
    autoPassRunning: () => autoPassTimer !== null,
    cancelAutoPassForThisWindow,
    clearSkipAttempt: () => { skipAttemptedForKey = null; },
    hasPriority,
    interactivePriority,
    paintCountdown,
    passButtonHtml,
    priorityBadgeHtml,
    priorityControlsHtml,
    railStopsHtml,
    railTimerHtml,
    resetSession: () => { stopsSynced = false; },
    stop: () => {
      stopAutoPass();
      autoPassWindowKey = null;
    },
    syncAutoPass,
    updateTimerSeconds,
    wireStopsPanel,
    yieldBadgeHtml,
    yieldButtonsHtml,
  };
}
