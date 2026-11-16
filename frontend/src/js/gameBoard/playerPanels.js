// Pure per-player panels: counters, static-effects list.

import { collectCostReductions } from './miscHtml.js';
import { t } from '../i18n.js';
import { escapeHtml, escapeAttr } from './html.js';

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

export function counterIcon(kind) {
  return PLAYER_COUNTER_ICONS[kind] || '🔘';
}

export function counterLabel(kind) {
  return PLAYER_COUNTER_LABELS[kind] || t('bd.counter.generic', { kind });
}

export function staticEffectsPanelHtml(view, s) {
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

export function playerCountersHtml(p, s, view) {
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
  const cmd = commanderDamageHtml(p.commander_damage, view);
  if (!bits.length && !cmd) return '';
  return `<div class="gf-pcounters">${bits.join('')}${cmd}</div>`;
}

export function commanderDamageHtml(commanderDamage, view) {
  const entries = Object.entries(commanderDamage || {});
  if (!entries.length) return '';
  return entries
    .map(([sourceId, e]) => {
      const state = view?.state;
      const visible = [...(state?.battlefield || []), ...(state?.players || []).flatMap(p =>
        [...(p.command || []), ...(p.graveyard || []), ...(p.exile || []), ...(p.hand || [])])];
      const source = visible.find(o => String(o.instance_id) === sourceId);
      const owner = state?.players?.find(p => p.id === source?.owner_id);
      const name = e.name || source?.name || `#${sourceId}`;
      const identity = owner ? `${name} · ${owner.name}` : `${name} · #${sourceId}`;
      const lethal = e.amount >= 21 ? ' gf-cmd-dmg--lethal' : '';
      return `<span class="gf-cmd-dmg${lethal}" data-commander-source="${escapeAttr(sourceId)}" data-hover-card="${escapeAttr(name)}" title="${escapeAttr(t('bd.cmdDmg.title', { name: identity }))}">👑 <span class="gf-cmd-source">${escapeHtml(identity)}</span> ${e.amount}/21</span>`;
    })
    .join('');
}
