// Card, battlefield, hand and stack rendering.
// A factory over `ctx` like choices.js: the renderers read live board state (view, drafts, overlays, image assets)
// through the board's getter/setter context.

import { GENERIC_TOKEN_KEY, cardImageUrl } from '../api.js';
import { cardActionButtons } from './cardActions.js';
import { effectSummaryHtml, unavailableCardActionsHtml } from './cardForms.js';
import { escapeAttr, escapeHtml } from './html.js';
import { exileCastableInfo, keywordAbbrev } from './cardHints.js';
import { getShowOpponentHand } from '../settings.js';
import { getState } from '../state.js';
import { isPlayableCardAction } from './dragDrop.js';
import { opponentHandToggleHtml } from './miscHtml.js';
import { renderOracleText } from '../cardTile.js';
import { t, tPlural } from '../i18n.js';


export function createCardRenderer(ctx) {
  const {
    playerName,
    render,
    selectedKickerAction,
    updateTargetOverlays,
    withBusy,
  } = ctx;

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
    if (o.attacking || ctx.attackDraft.has(o.instance_id)) classes.push('attacking');
    if (ctx.compactView) classes.push('compact-card');
    // RULE 115/601.2c: this object is the chosen target of something
    // currently on the stack — `updateTargetOverlays` (called once per
    // `render()`) reduces `s.stack[*].targets` to this instance-id set.
    if (ctx.targetedInstanceIds.has(o.instance_id)) classes.push('gf-targeted');
    // Two permanents each targeting the other (Fight-shaped abilities, or
    // two removal spells naming each other's source) get a distinct border
    // instead of just the plain target overlay, so the pairing itself reads
    // at a glance.
    if (ctx.mutualTargetPairIds.has(o.instance_id)) classes.push('gf-mutual-target');
    if (ctx.abilitySourceInstanceIds.has(o.instance_id)) classes.push('gf-ability-source');
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
    const menuId = `gf-card-menu-${o.instance_id}-${++ctx.cardMenuSerial}`;
    const attack = { draft: ctx.attackDraft, menuOpen: ctx.attackMenuOpen, busy: ctx.busy };
    const buttons = cardActionButtons(attackActions, attack);
    const menu = `<div id="${menuId}" popover="manual" class="gf-card-menu" aria-label="${escapeAttr(o.name)}">${menuActions.map(a => `<div class="gf-menu-option">${cardActionButtons([a], attack)}${a.type === 'cast_spell' ? `<span class="gf-menu-cost">${renderOracleText(a.effective_cost || a.cost_label || a.base_cost || o.mana_cost || '{0}')}</span>` : ''}</div>`).join('') || unavailableCardActionsHtml(o)}</div>`;
    const attackBadge = ctx.attackDraft.has(o.instance_id)
      ? `<span class="gf-attacking-badge">⚔️ ${escapeHtml(t('bd.attack.selected'))}${ctx.attackDraft.get(o.instance_id).defender_label ? ` → ${escapeHtml(ctx.attackDraft.get(o.instance_id).defender_label)}` : ''}</span>`
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
    const targetOverlay = ctx.targetedInstanceIds.has(o.instance_id)
      ? `<span class="gf-target-overlay" title="${escapeAttr(t(ctx.mutualTargetPairIds.has(o.instance_id) ? 'bd.badge.mutualTargetTitle' : 'bd.badge.targetedTitle'))}">🎯</span>`
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

    const rows = ctx.threeRows
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

  function objGrid(objs, empty, byInstance = {}, pending = null) {
    if (!objs.length) return `<p class="empty-state">${empty}</p>`;
    const imageCache = getState().imageCache;
    return `<div class="card-grid">${objs
      .map((o) => objCard(o, imageCache, pending ? [] : byInstance[o.instance_id] || []))
      .join('')}</div>`;
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
    if (o.face_down_in_exile) return ctx.assetsSleeveImageUrl || null;
    // RULE 708.2: a face-down permanent (morph/disguise/manifest/cloak) is a
    // 2/2 with no identity at all — the backend already ships only the
    // synthetic face (`game/face_down.py`), so there is nothing to leak, but
    // there is also no art to show: render the player's card back. This is
    // the case the sleeve fallback below was written for before any state
    // could actually reach it.
    if (o.face_down) return ctx.assetsSleeveImageUrl || null;
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
      const custom = ctx.tokenImages[(o.name || '').toLowerCase()];
      if (custom) return custom;
      // A face-down/transformed token (e.g. a token copy of a flipped DFC,
      // RULE 707) has no real art for its back — fall back to the
      // player's chosen sleeve backside instead of a blank tile.
      if (showBack && ctx.assetsSleeveImageUrl) return ctx.assetsSleeveImageUrl;
      // No specific art for this token by name (typically an ad hoc token
      // an effect synthesized inline, e.g. "1/1 white Soldier", which has
      // no catalogue entry to upload art against by exact name) — the
      // player's "generic" token image (settings.js) covers all of these.
      return ctx.tokenImages[GENERIC_TOKEN_KEY] || null;
    }
    if (!o.card_id) return null;
    return cardImageUrl(o.card_id, 'small', showBack ? 'back' : 'front');
  }

  // Whether this permanent's tile should currently show its *back* face —
  // its real transformed state (RULE 712.6), inverted by a client-only
  // "🔄 peek" toggle (`flippedForView`) that doesn't touch game state.
  function showsBackFace(o) {
    return ctx.flippedForView.has(o.instance_id) ? !o.transformed : !!o.transformed;
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
    const ghosts = ctx.resolvedGhosts
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

  // One face-down card: the player's own chosen sleeve if they uploaded one
  // (Einstellungen tab, `setAssets`), otherwise a plain patterned back.
  function faceDownCardHtml(label = t('bd.hand.faceDownAlt')) {
    if (ctx.assetsSleeveImageUrl) {
      return `<div class="card has-image gf-face-down"><img src="${escapeAttr(ctx.assetsSleeveImageUrl)}" alt="${escapeAttr(label)}" /></div>`;
    }
    return `<div class="card gf-face-down" title="${escapeAttr(label)}"></div>`;
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
    const open = ctx.expandedZones.has(key);
    return `
      <div class="gf-zone ${cls}">
        <h4><button type="button" class="gf-zone-toggle" data-zone-toggle="${escapeAttr(key)}" aria-expanded="${open ? 'true' : 'false'}"><span class="gf-zone-caret">${open ? '▾' : '▸'}</span> ${escapeHtml(label)} (${count})</button></h4>
        <div class="gf-zone-body"${open ? '' : ' hidden'}>${bodyHtml}</div>
      </div>`;
  }

  function blindSideboardHtml(player, state) {
    const slots = (ctx.view.legal_actions || []).filter(a => a.blind_sideboard && player.id === ctx.view.acting_as);
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

  // `objs` in the player's own drag-and-drop order for `zoneKey`; cards the
  // order doesn't know yet (just drawn / entered) go to the end.
  function orderedByLocal(zoneKey, objs) {
    const byId = new Map(objs.map((o) => [o.instance_id, o]));
    const order = (ctx.zoneOrder.get(zoneKey) || []).filter((id) => byId.has(id));
    for (const o of objs) if (!order.includes(o.instance_id)) order.push(o.instance_id);
    ctx.zoneOrder.set(zoneKey, order);
    return order.map((id) => byId.get(id));
  }

  return {
    objCard,
    battlefieldHtml,
    handHtml,
    objGrid,
    exileCastableHtml,
    graveCastableHtml,
    handAreaHtml,
    resolveImageUrl,
    showsBackFace,
    stackItemHtml,
    railStackHtml,
    stackKindBadge,
    spellTypeLabel,
    faceDownCardHtml,
    collapsibleZoneHtml,
    blindSideboardHtml,
    orderedByLocal,
  };
}
