// Pure drag-and-drop helpers: which actions/targets a dragged card maps to.

export function isPlayableCardAction(a) {
  return a.type === 'cast_spell' || a.type === 'play_land' || a.type === 'activate_ability';
}

export function dragTargetsForActions(actions) {
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

export function findDragTarget(element) {
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
