// Drag-and-drop on the board: dragging a card onto a drop zone casts/plays/activates it, and the
// local reorder of hand and battlefield rows. A factory over `ctx`; `dragSource` is reassigned as drags start and end.

import { actionHasCostPick, findTargetOptionForAction } from './castForm.js';
import { dragTargetsForActions, findDragTarget, isPlayableCardAction } from './dragDrop.js';

export function createDragController(ctx) {
  const {
    act,
    confirmReplacementOrder,
    confirmTriggerOrder,
    readKicker,
    readKickerAnnouncement,
    readKickerX,
    readX,
    render,
    selectedKickerAction,
    wire,
    prepareCastTargeting,
  } = ctx;

  function wireCardActionsAndDrag() {
    ctx.root.querySelectorAll('[data-action]').forEach((el) => {
      el.addEventListener('click', () => {
        const action = JSON.parse(el.dataset.action);
        if (action.type === 'declare_attackers') {
          const iid = action.instance_ids[0];
          ctx.attackDraft.set(iid, action);
          ctx.attackMenuOpen.delete(iid);
          render();
          return;
        }
        act(action);
      });
    });

    if (!ctx.dragHandlersInstalled) {
      ctx.dragHandlersInstalled = true;
      ctx.root.addEventListener('dragover', (e) => {
        e.preventDefault();
        if (e.dataTransfer) e.dataTransfer.dropEffect = 'move';
        const target = maybeReadDropTargetData(e.target);
        if (!target) return;
      });
      ctx.root.addEventListener('drop', (e) => {
        // A drop on a specific valid target (equip onto a creature) is a real
        // game action; any other drop inside the card's own zone only re-sorts
        // the local presentation order.
        const zoneEl = e.target.closest('[data-order-zone]');
        if (ctx.dragSource && zoneEl && zoneEl.dataset.orderZone === ctx.dragSource.zone
            && !['instance', 'player'].includes(maybeReadDropTargetData(e.target)?.type)) {
          e.preventDefault();
          const order = ctx.zoneOrder.get(ctx.dragSource.zone) || [];
          let targetSlot = e.target.closest('[data-instance-id]');
          // Dropped on an attachment: its host is what sits in the row.
          // `dataset` values are strings, instance ids on the wire may be numbers.
          const indexOfId = (id) => order.findIndex((known) => String(known) === String(id));
          if (targetSlot && indexOfId(targetSlot.dataset.instanceId) < 0) {
            targetSlot = targetSlot.closest('.gf-attach-group')?.querySelector('[data-instance-id]') || null;
          }
          const targetId = targetSlot?.dataset.instanceId;
          const from = indexOfId(ctx.dragSource.instanceId);
          const to = targetId ? indexOfId(targetId) : order.length - 1;
          if (from >= 0 && to >= 0 && from !== to) {
            order.splice(to, 0, order.splice(from, 1)[0]);
          }
          ctx.dragSource = null;
          clearDragHighlights();
          render();
          return;
        }
        const target = maybeReadDropTargetData(e.target);
        e.preventDefault();
        if (target) {
          executeDroppedAction(target);
        }
        ctx.dragSource = null;
        clearDragHighlights();
      });
    }

    ctx.root.querySelectorAll('[data-draggable-card="true"]').forEach((el) => {
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
        ctx.dragSource = {
          instanceId,
          playerId: slot.closest('[data-player-id]')?.dataset.playerId || null,
          zone: slot.closest('[data-order-zone]')?.dataset.orderZone || null,
        };
        e.dataTransfer.effectAllowed = 'move';
        e.dataTransfer.setData('text/plain', '');
        highlightDragTargets();
      });
      el.addEventListener('dragend', () => {
        ctx.dragSource = null;
        clearDragHighlights();
      });
    });

    // RULE 616.1 replacement-order popup: drag & drop reordering. Dragging
    // reorders the list purely client-side (`replacementOrderDraft` is only
    // read again on the next render/confirm); "Bestätigen" replays the final
    // order via `confirmReplacementOrder`.
    const reorderList = ctx.root.querySelector('.gf-reorder-list');
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
      ctx.root.querySelector('[data-reorder-confirm]')?.addEventListener('click', () => {
        const order = Array.from(reorderList.querySelectorAll('.gf-reorder-item')).map((li) => li.dataset.id);
        confirmReplacementOrder(order);
      });
      // RULE 603.3b trigger-order popup shares the same `.gf-reorder-list`
      // drag mechanics above; only the confirm step differs — items carry
      // `data-key` (a stable `triggerOptionKey`, not a round-numbered id).
      ctx.root.querySelector('[data-trigger-order-confirm]')?.addEventListener('click', () => {
        const order = Array.from(reorderList.querySelectorAll('.gf-reorder-item')).map((li) => li.dataset.key);
        confirmTriggerOrder(order);
      });
    }
  }

  function executeDroppedAction(target) {
    if (!ctx.dragSource || !target) return;
    const actions = dragActionsForInstance(ctx.dragSource.instanceId);
    if (!actions.length) return;

    // RULE 700.2: a drop must not silently announce the first mode. Show
    // all server-provided modes, including ones that need targets elsewhere.
    if (actions.some(a => (a.type === 'cast_spell' || a.type === 'activate_ability') && a.mode != null)) {
      const slot = ctx.root?.querySelector(`[data-card-menu][data-instance-id="${CSS.escape(ctx.dragSource.instanceId)}"]`);
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
        send.kicked = readKickerAnnouncement(action.instance_id, action.face, action.splice_ids);
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

  function highlightDragTargets() {
    clearDragHighlights();
    if (!ctx.dragSource) return;
    const actions = dragActionsForInstance(ctx.dragSource.instanceId);
    if (!actions.length) return;
    const targets = dragTargetsForActions(actions);
    const getByInstance = (id) => ctx.root?.querySelector(`[data-instance-id="${CSS.escape(id)}"]`);
    for (const id of targets.instanceIds) {
      const el = getByInstance(id);
      if (el) el.classList.add('gf-drag-target-valid');
    }
    for (const id of targets.playerIds) {
      const el = ctx.root?.querySelector(`[data-player-id="${CSS.escape(id)}"]`);
      if (el) el.classList.add('gf-drag-target-valid');
    }
    if (targets.battlefield) {
      // Scoped to the dragged card's *own* board — a shared/multiplayer view
      // renders one battlefield per player, and an unscoped querySelector
      // would always find whichever one happens to come first in
      // `boardOrder` (never this client's own, which is drawn last),
      // highlighting the wrong player's battlefield whenever they aren't it.
      const ownBoard = ctx.dragSource.playerId
        ? ctx.root?.querySelector(`[data-player-id="${CSS.escape(ctx.dragSource.playerId)}"]`)
        : ctx.root;
      const battlefield = ownBoard?.querySelector('[data-drop-zone="battlefield"]');
      if (battlefield) battlefield.classList.add('gf-drag-target-valid');
    }
    const sourceEl = ctx.root?.querySelector(`[data-instance-id="${CSS.escape(ctx.dragSource.instanceId)}"]`);
    if (sourceEl) sourceEl.classList.add('gf-drag-source');
  }

  function clearDragHighlights() {
    ctx.root?.querySelectorAll('.gf-drag-target-valid, .gf-drag-source').forEach((el) => {
      el.classList.remove('gf-drag-target-valid', 'gf-drag-source');
    });
  }

  function isValidDragTarget(target) {
    if (!ctx.dragSource || !target) return false;
    const actions = dragActionsForInstance(ctx.dragSource.instanceId);
    if (!actions.length) return false;
    const targets = dragTargetsForActions(actions);
    if (target.type === 'battlefield') {
      if (!targets.battlefield) return false;
      // A played land/permanent always joins *this card's own controller's*
      // battlefield — never another player's board, however many are on
      // screen — so a drop only counts here if it landed on that same
      // player's own battlefield section (see the `dragstart` handler).
      if (!ctx.dragSource.playerId) return true;
      return target.element?.closest('[data-player-id]')?.dataset.playerId === ctx.dragSource.playerId;
    }
    if (target.type === 'instance') return targets.instanceIds.has(target.instanceId);
    if (target.type === 'player') return targets.playerIds.has(target.playerId);
    return false;
  }

  function dragActionsForInstance(instanceId) {
    if (!ctx.latestByInstance || !ctx.latestByInstance[instanceId]) return [];
    return ctx.latestByInstance[instanceId].filter(isPlayableCardAction).map((action) => selectedKickerAction(action)).filter((action) => !action.locked);
  }

  function maybeReadDropTargetData(element) {
    if (!element) return null;
    const target = findDragTarget(element);
    return target && isValidDragTarget(target) ? target : null;
  }

  return {
    wireCardActionsAndDrag,
    executeDroppedAction,
    highlightDragTargets,
    clearDragHighlights,
    isValidDragTarget,
    dragActionsForInstance,
    maybeReadDropTargetData,
  };
}
