// Pure helpers for stack entries and resolved-ghost bookkeeping.

// A stable-ish signature for one stack item, for spotting which entries
// disappeared between two views (i.e. resolved / were countered) so they
// can linger a moment as greyed-out ghosts in the rail.
export function stackItemSig(item) {
  const obj = item.object || item.source || {};
  return `${obj.instance_id ?? ''}|${item.description || ''}|${item.kind || ''}|${obj.name || ''}`;
}

/** A ghost item's card name (spell card, or ability source). */
export function ghostItemName(item) {
  return (item.object || item.source || {}).name || '';
}

// A bot opponent's cast/activation is drained off the stack by the server
// before the client ever sees a view with it on the stack (`run_bots` in
// multiplayer, `_advance_solo_bots` in solo, both answer to completion
// before returning) — so the stack-diff above never fires a ghost for it.
// Build a minimal synthetic stack item from the `move_log` label instead
// so it still flashes up in the rail as a resolved ghost. `null` for
// labels that don't put anything on the stack (play_land, pass_priority…).
export function syntheticStackItemFromMoveLabel(label) {
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
