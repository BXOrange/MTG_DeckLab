// Pending-choice popups and the small helpers they share (player names, target controller chips).
// A factory because the renderers read live board state: `ctx` is a getter/setter object the board
// builds once, so reassigned drafts and `view` are always current (and drafts can be reset while rendering).

import { CHOICE_ICONS, TARGET_CHOICE_KINDS, TARGET_OWNER_ZONES } from './labels.js';
import { bannerStyle } from '../bannerColors.js';
import { cardImageUrl } from '../api.js';
import { castTargetHtml, lookTopChoiceHtml } from './cardForms.js';
import { escapeAttr, escapeHtml, printingHoverAttr } from './html.js';
import { measurementValue, triggerOptionKey } from './miscHtml.js';
import { t } from '../i18n.js';

export function createChoiceRenderer(ctx) {
  function playerName(id) {
    const p = (ctx.view.state?.players || []).find((pl) => pl.id === id);
    return p ? p.name : id;
  }

  // VIS-13: which player controls a target candidate. A permanent's
  // controller (RULE 108.4) is on the battlefield; a spell/ability on the
  // stack carries its own controller; a card in a hand/graveyard/exile
  // zone has no controller, so its owner stands in. Players are their own
  // candidates and need no tag. The server only puts `controller_id` on some
  // descriptors, so the view is the one source that covers every kind.
  function targetControllerId(o) {
    if (!o || o.player_id != null || o.instance_id == null) return null;
    if (o.controller_id != null) return o.controller_id;
    const s = ctx.view.state;
    if (!s) return null;
    const onBattlefield = (s.battlefield || []).find((x) => x.instance_id === o.instance_id);
    if (onBattlefield) return onBattlefield.controller_id;
    const onStack = (s.stack || []).find(
      (it) => (it.object?.instance_id ?? it.source?.instance_id) === o.instance_id,
    );
    if (onStack) return onStack.controller_id ?? null;
    for (const pl of s.players || []) {
      for (const zone of TARGET_OWNER_ZONES) {
        if ((pl[zone] || []).some((x) => x.instance_id === o.instance_id)) return pl.id;
      }
    }
    return null;
  }

  // The controller tag shown beside a target candidate: the player's name in
  // their banner colour, "(you)" for the viewer's own seat.
  function targetControllerChipHtml(o) {
    const id = targetControllerId(o);
    if (id == null) return '';
    const mine = ctx.view.perspective != null && id === ctx.view.perspective;
    const label = mine ? t('bd.target.controllerMine', { name: playerName(id) }) : playerName(id);
    const css = bannerStyle(ctx.seatStatus(id)?.banner_color);
    return `<span class="gf-target-ctrl${mine ? ' gf-target-ctrl--mine' : ''}${css ? ' gf-banner-tinted' : ''}"${css ? ` style="${escapeAttr(css)}"` : ''} title="${escapeAttr(t('bd.target.controllerTitle', { name: playerName(id) }))}">${escapeHtml(label)}</span>`;
  }

  // A pending choice is rendered as a modal popup for the deciding player:
  // the board behind it is dimmed/locked (`.goldfish.choosing`) so the only
  // thing to do is answer. Each server-provided option becomes one button —
  // except `replacement_order` (RULE 616.1) and `order_triggers`
  // (RULE 603.3b), which get a drag-and-drop reorderable list instead (see
  // `replacementOrderHtml`/`triggerOrderHtml`), and `scry`/`surveil`, which
  // get inline card-face thumbnails instead of bare name buttons (see
  // `lookTopChoiceHtml`). `aside` is a push-aside escape hatch
  // (`data-choice-aside` below) — a player deciding e.g. a surveil may want
  // to check the board (a graveyard, a permanent's text) before answering
  // rather than being fully blocked.
  function pendingChoiceHtml(pending, aside = false) {
    const icon = CHOICE_ICONS[pending.kind] || '❔';
    const heading = pending.kind === 'proliferate' ? t('bd.proliferate.title')
      : pending.prompt || pending.description || t('bd.choice.needed');
    const body = pending.kind === 'proliferate'
      ? proliferateChoiceHtml(pending)
      : pending.kind === 'graveyard_replacement'
      ? graveyardReplacementHtml(pending)
      : ['physical_property_measurement', 'physical_environment_measurement'].includes(pending.kind)
      ? physicalMeasurementHtml(pending)
      : pending.kind === 'replacement_order'
      ? replacementOrderHtml(pending)
      : pending.kind === 'order_triggers'
        ? triggerOrderHtml(pending)
        : pending.kind === 'scry' || pending.kind === 'surveil' || pending.kind === 'reorder_top' || pending.kind === 'look_hand'
          ? lookTopChoiceHtml(pending)
          : pending.kind === 'clash'
            ? clashChoiceHtml(pending)
          // MEC-46: a "vote for one of these objects" ballot (Council's
          // Judgment / Custodi Squire) — options carry a `card_id`, so the
          // same face-thumbnail renderer scry/surveil use reads far better
          // than bare name buttons.
          : pending.kind === 'vote_object'
            ? lookTopChoiceHtml(pending)
            : simpleChoiceButtonsHtml(pending);
    const asideLabel = aside ? t('bd.choice.asideShow') : t('bd.choice.asidePush');
    const contributions = Object.entries(pending.paid_amounts || {})
      .filter(([, amount]) => amount > 0)
      .map(([id, amount]) => `${playerName(id)} (${amount})`)
      .join(', ');

    return `
      <div class="gf-modal-overlay${aside ? ' aside' : ''}">
        <div class="gf-modal" role="dialog" aria-modal="true">
          <div class="gf-modal-head">
            <span class="gf-modal-icon">${icon}</span>
            <div>
              <h4>${escapeHtml(heading)}</h4>
              <p class="gf-modal-who">${escapeHtml(t('bd.choice.forWhom', { name: playerName(pending.player_id) }))}</p>
              ${pending.source_name ? `<p class="gf-modal-source">${escapeHtml(t('bd.choice.triggeredBy', { name: pending.source_name }))}</p>` : ''}
            </div>
            <button type="button" class="gf-modal-aside" data-choice-aside title="${escapeAttr(t('bd.choice.asideTitle'))}">${asideLabel}</button>
          </div>
          ${pending.kind === 'amount_payment' && pending.resource === 'mana'
            && ctx.view.legal_actions?.some(a => a.type === 'tap_for_mana' || a.type === 'activate_hand_mana')
            ? `<p>${escapeHtml(t('bd.choice.amountPaymentMana'))}</p>` : ''}
          ${contributions ? `<p>${escapeHtml(t('bd.choice.amountPaymentPaid', { contributions }))}</p>` : ''}
          ${body}
        </div>
      </div>
    `;
  }

  function proliferateChoiceHtml(pending) {
    const options = (pending.options || []).filter(o => o.id !== 'decline');
    if (ctx.proliferateDraft.key !== pending.selection_id) {
      ctx.proliferateDraft = { key: pending.selection_id, ids: new Set(pending.recommended_ids || []) };
    }
    const rows = options.map(option => {
      const player = (ctx.view.state.players || []).find(p => p.id === option.player_id);
      const object = (ctx.view.state.battlefield || []).find(o => o.instance_id === option.instance_id);
      const counters = { ...(player?.counters || object?.counters || {}) };
      if (player?.poison) counters.poison = player.poison;
      const marks = Object.entries(counters).filter(([,n]) => n > 0).map(([kind,n]) => `${kind}: ${n} → ${Number(n) + 1}`).join(', ');
      const owner = object ? playerName(object.controller_id) : playerName(option.player_id);
      return `<label class="gf-proliferate-option">
        <input type="checkbox" data-proliferate-option="${escapeAttr(option.id)}" ${ctx.proliferateDraft.ids.has(option.id) ? 'checked' : ''} ${ctx.busy ? 'disabled' : ''}>
        <span><strong>${escapeHtml(option.label)}</strong>${object ? ` · ${escapeHtml(owner)}` : ''}<br><small>${escapeHtml(marks)}</small></span>
      </label>`;
    }).join('');
    return `<p>${escapeHtml(t('bd.proliferate.hint'))}</p>
      <div class="gf-proliferate-options">${rows}</div>
      <div class="gf-choice-options">
        <button type="button" data-proliferate-reset ${ctx.busy ? 'disabled' : ''}>${t('bd.proliferate.recommend')}</button>
        <button type="button" data-proliferate-clear ${ctx.busy ? 'disabled' : ''}>${t('bd.proliferate.clear')}</button>
        <button type="button" class="primary" data-proliferate-confirm ${ctx.busy ? 'disabled' : ''}>${t('bd.proliferate.confirm')}</button>
      </div>`;
  }

  // RULE 616.1: the chooser ticks which cards of a simultaneous batch take Dauthi Voidwalker's void-counter exile;
  // nothing ticked (the default) is the plain exile. Reuses the proliferate draft and its change/confirm handlers.
  function graveyardReplacementHtml(pending) {
    const options = (pending.options || []).filter(o => o.id !== 'decline');
    if (ctx.proliferateDraft.key !== pending.selection_id) ctx.proliferateDraft = { key: pending.selection_id, ids: new Set() };
    const rows = options.map(option => `<label class="gf-proliferate-option">
        <input type="checkbox" data-proliferate-option="${escapeAttr(option.id)}" ${ctx.proliferateDraft.ids.has(option.id) ? 'checked' : ''} ${ctx.busy ? 'disabled' : ''}>
        <span><strong>${escapeHtml(option.label)}</strong></span>
      </label>`).join('');
    return `<p>${escapeHtml(t('bd.graveyardReplacement.hint'))}</p>
      <div class="gf-proliferate-options">${rows}</div>
      <div class="gf-choice-options">
        <button type="button" data-proliferate-clear ${ctx.busy ? 'disabled' : ''}>${t('bd.graveyardReplacement.none')}</button>
        <button type="button" class="primary" data-proliferate-confirm ${ctx.busy ? 'disabled' : ''}>${t('bd.proliferate.confirm')}</button>
      </div>`;
  }

  function physicalMeasurementHtml(pending) {
    const subject = pending.subject || {};
    const key = JSON.stringify([pending.kind, pending.observation_id, pending.property, subject.printing_id, subject.face]);
    if (ctx.measurementDraft.key !== key) ctx.measurementDraft = { key, text: '' };
    const environmental = pending.kind === 'physical_environment_measurement';
    const text = ctx.measurementDraft.text;
    const valid = measurementValue(text, pending) !== null;
    const image = subject.image_url || (subject.printing_id
      ? cardImageUrl(subject.printing_id, 'normal', subject.face || 'front') : null);
    return `<form data-physical-measurement novalidate>
      ${image ? `<img src="${escapeAttr(image)}" alt="${escapeAttr(subject.name || '')}" width="300" style="max-width:100%;height:auto">` : ''}
      <p>${escapeHtml(subject.name || '')}</p>
      ${environmental ? '' : `<p>${escapeHtml(subject.printing_label
        ? t('bd.measurement.printing', { printing: subject.printing_label, face: subject.face || 'front' })
        : t('bd.measurement.face', { face: subject.face || 'front' }))}</p>`}
      <p>${escapeHtml(t(environmental ? 'bd.measurement.mirrorsInstructions' : 'bd.measurement.instructions'))}</p>
      <label>${escapeHtml(t(environmental ? 'bd.measurement.mirrors' : 'bd.measurement.lines'))}
        <input data-measurement-value type="text" inputmode="numeric" pattern="[0-9]+" autocomplete="off" required
          value="${escapeAttr(text)}" aria-describedby="gf-measurement-error" ${ctx.busy ? 'disabled' : ''}>
      </label>
      <p id="gf-measurement-error" data-measurement-error role="status">${text && !valid ? escapeHtml(t('bd.measurement.invalid')) : ''}</p>
      <button type="submit" class="primary" data-measurement-submit ${ctx.busy || !valid ? 'disabled' : ''}>${escapeHtml(t(environmental ? 'bd.measurement.confirmObservation' : 'bd.measurement.confirm'))}</button>
    </form>`;
  }

  function simpleChoiceButtonsHtml(pending) {
    const options = pending.options
      || (pending.eligible || []).map((e) => ({ id: String(e.instance_id), label: e.name, instance_id: e.instance_id }));

    const buttons = options
      .map((opt) => {
        if (opt.action?.type === 'cast_spell') return `<span>${escapeHtml(opt.action.name || '')}</span>${castTargetHtml(opt.action)}`;
        if (opt.id === 'decline') {
          const action = JSON.stringify({ type: 'decline' });
          return `<button type="button" class="gf-decline" data-action='${escapeAttr(action)}'>${escapeHtml(opt.label || t('bd.choice.chooseNothing'))}</button>`;
        }
        const action = JSON.stringify(opt.action || { type: 'choose', option_id: opt.id, instance_id: opt.instance_id, name: opt.label });
        const hover = opt.instance_id != null ? ` data-hover-card="${escapeHtml(opt.label || '')}"${printingHoverAttr(opt.card_id)}` : '';
        // VIS-13: a RULE 115 target offered through the generic choice popup
        // (`trigger_target`) says who controls each candidate.
        const chip = TARGET_CHOICE_KINDS.has(pending.kind) ? targetControllerChipHtml(opt) : '';
        return `<button type="button"${hover} data-action='${escapeAttr(action)}'>${escapeHtml(opt.label || opt.id)}${chip}</button>`;
      })
      .join('');

    return `<div class="gf-choice-options">${buttons}</div>${choiceTextHtml(pending)}`;
  }

  // PAR-203: a choice whose answer space is not enumerable (a card name, RULE 201.3; a creature type, RULE 205.3m)
  // offers the options above as suggestions and lets the player type any legal answer.
  function choiceTextHtml(pending) {
    if (!pending.free_text) return '';
    const key = JSON.stringify([pending.kind, pending.source_id, pending.what, pending.prompt]);
    if (ctx.choiceTextDraft.key !== key) ctx.choiceTextDraft = { key, text: '' };
    return `<form class="gf-choice-text" data-choice-text novalidate>
      <label>${escapeHtml(t('bd.choice.typeLabel'))}
        <input data-choice-text-value type="text" autocomplete="off" value="${escapeAttr(ctx.choiceTextDraft.text)}" ${ctx.busy ? 'disabled' : ''}>
      </label>
      <button type="submit" class="primary" data-choice-text-submit ${ctx.busy || !ctx.choiceTextDraft.text.trim() ? 'disabled' : ''}>${escapeHtml(t('bd.choice.typeSubmit'))}</button>
    </form>`;
  }

  // RULE 701.30c: both clash cards are public while their owners decide,
  // even though they are still physically in hidden libraries.  The server
  // sends them separately as `state.clash_revealed`; show both faces here,
  // then offer only this pending choice's owner the top/bottom decision.
  function clashChoiceHtml(pending) {
    const revealed = ctx.view.state?.clash_revealed || [];
    const faces = revealed.map((card) => {
      const img = card.card_id ? cardImageUrl(card.card_id, 'small', 'front') : null;
      return `<article class="gf-clash-card" data-hover-card="${escapeHtml(card.name || '')}"${printingHoverAttr(card.card_id)}>
        ${img ? `<img class="gf-lt-card-img" src="${escapeAttr(img)}" alt="${escapeAttr(card.name || '')}" loading="lazy">` : ''}
        <span class="gf-lt-card-label">${escapeHtml(card.name || 'Karte')}</span>
      </article>`;
    }).join('');
    const buttons = (pending.options || []).map((opt) => {
      const action = JSON.stringify({ type: 'choose', option_id: opt.id, name: opt.label });
      return `<button type="button" class="${opt.id === 'bottom' ? 'gf-decline' : 'primary'}" data-action='${escapeAttr(action)}'>${escapeHtml(opt.label || opt.id)}</button>`;
    }).join('');
    return `<div class="gf-clash-reveal">${faces}</div><div class="gf-choice-options">${buttons}</div>`;
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
    if (!ctx.replacementOrderDraft
        || ctx.replacementOrderDraft.length !== ids.length
        || !ids.every((id) => ctx.replacementOrderDraft.includes(id))) {
      ctx.replacementOrderDraft = ids.slice();
    }
    const byId = Object.fromEntries(options.map((o) => [o.id, o]));
    const items = ctx.replacementOrderDraft
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
      <p class="gf-reorder-hint">${t('bd.reorder.hintEffects')}</p>
      <ul class="gf-reorder-list">${items}</ul>
      <div class="gf-modal-foot">
        <button type="button" class="primary" data-reorder-confirm>${t('bd.common.confirm')}</button>
      </div>
    `;
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
    if (!ctx.triggerOrderDraft
        || ctx.triggerOrderDraft.length !== keys.length
        || !keys.every((k) => ctx.triggerOrderDraft.includes(k))) {
      ctx.triggerOrderDraft = keys.slice();
    }
    const byKey = Object.fromEntries(options.map((o) => [triggerOptionKey(o), o]));
    const items = ctx.triggerOrderDraft
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
      <p class="gf-reorder-hint">${t('bd.reorder.hintTriggers')}</p>
      <ul class="gf-reorder-list gf-trigger-order-list">${items}</ul>
      <div class="gf-modal-foot">
        <button type="button" class="primary" data-trigger-order-confirm>${t('bd.common.confirm')}</button>
      </div>
    `;
  }

  return {
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
  };
}
