export function wireBoardGeometry({ root, view, attackDraft, blockDraft }) {
  const svg = root.querySelector('.gf-connection-lines');
  const find = (attr, id) => root.querySelector(`[${attr}="${CSS.escape(String(id))}"]`);
  const card = id => find('data-instance-id', id)?.querySelector('.card');
  const stack = id => find('data-stack-id', id)?.querySelector('.card');
  const draw = () => {
    if (!svg || !view()) return;
    const lines = [];
    const connect = (from, to, kind) => {
      if (!from || !to) return;
      const a = from.getBoundingClientRect(), b = to.getBoundingClientRect();
      if (!a.width || !b.width) return;
      const offset = kind === 'block' ? 5 : 0;
      lines.push(`<line class="gf-connection--${kind}" x1="${a.x + a.width / 2 + offset}" y1="${a.y + a.height / 2 + offset}" x2="${b.x + b.width / 2 + offset}" y2="${b.y + b.height / 2 + offset}" />`);
    };
    const currentView = view();
    for (const item of currentView.state.stack || []) {
      const source = card(item.source?.instance_id) || stack(item.stack_id);
      for (const target of item.targets || []) {
        const destination = target.instance_id != null ? card(target.instance_id) || find('data-stack-instance-id', target.instance_id)?.querySelector('.card')
          : target.player_id != null ? find('data-player-id', target.player_id)?.querySelector('.gf-player-board-head') || find('data-player-id', target.player_id)
          : stack(target.stack_id);
        connect(source, destination, 'target');
      }
    }
    for (const object of currentView.state.battlefield || []) {
      const draft = attackDraft.get(object.instance_id);
      const defender = draft ? draft.defender : object.attacking ? object.combat_defender : null;
      if (defender) {
        const destination = defender.kind === 'player'
          ? find('data-player-id', defender.id)?.querySelector('.life-total, .gf-opp-life')
          : card(defender.instance_id);
        connect(card(object.instance_id), destination, 'attack');
      }
      const attackers = blockDraft.has(object.instance_id) ? [blockDraft.get(object.instance_id)]
        : [object.blocking, ...(object.additional_blocking || [])].filter(id => id != null);
      for (const attacker of attackers) connect(card(object.instance_id), card(attacker), 'block');
    }
    svg.innerHTML = lines.join('');
  };
  const controller = new AbortController();
  const closeMenus = event => root.querySelectorAll('.gf-card-menu:popover-open').forEach(menu => {
    if (event.type === 'keydown' ? event.key === 'Escape' : !menu.contains(event.target)) menu.hidePopover();
  });
  document.addEventListener('pointerdown', closeMenus, { signal: controller.signal });
  document.addEventListener('keydown', closeMenus, { signal: controller.signal });
  window.addEventListener('scroll', draw, { capture: true, signal: controller.signal });
  window.addEventListener('resize', draw, { signal: controller.signal });
  const observer = new ResizeObserver(draw);
  observer.observe(root);
  root.addEventListener('load', draw, { capture: true, signal: controller.signal });
  draw();
  return () => {
    controller.abort();
    observer.disconnect();
  };
}
