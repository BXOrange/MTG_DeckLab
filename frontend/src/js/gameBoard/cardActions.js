// Action buttons for a card (cast/activate/attack/loyalty ...). Pure: board state it needs arrives via the `attack` argument.

import { actionButton, defenderPayload, kickerFieldHtml, manaOptionLabel, replicateFieldsHtml, xKey } from './castForm.js';
import { castTargetHtml, colorSplitHtml, manaChoiceControlHtml } from './cardForms.js';
import { faceHint, giftHint, loyaltyModifierClass, modeHint } from './cardHints.js';
import { renderOracleText } from '../cardTile.js';
import { t } from '../i18n.js';
import { escapeHtml, escapeAttr } from './html.js';

export function attackControlHtml(a, attack) {
  const defenders = a.legal_defenders || [];
  const iid = a.instance_id;
  if (attack.draft.has(iid)) {
    return `<button type="button" class="gf-card-action" data-attack-remove="${iid}" ${attack.busy ? 'disabled' : ''}>✕ ${t('bd.attack.deselect')}</button>`;
  }
  const attackAction = (defender, index) => ({
    type: 'declare_attackers', instance_ids: [iid],
    ...(defender ? { defender: defenderPayload(defender) } : {}),
    attack_tax_amount: a.attack_tax_amounts?.[index] || 0,
    attack_life_amount: a.attack_life_amounts?.[index] || 0,
    name: a.name,
    defender_label: defender?.label,
  });
  if (defenders.length === 0) {
    return actionButton(
      attackAction(null, 0),
      '⚔️ Angreifen'
    );
  }
  if (defenders.length === 1) {
    const d = defenders[0];
    return actionButton(
      attackAction(d, 0),
      `⚔️ Angreifen → ${escapeHtml(d.label)}`
    );
  }
  const open = attack.menuOpen.has(iid);
  const menu = open
    ? `<div class="gf-attack-defenders">${defenders
        .map((d, index) =>
          actionButton(
            attackAction(d, index),
            `→ ${escapeHtml(d.label)}`
          )
        )
        .join('')}</div>`
    : '';
  return `<button type="button" class="gf-card-action" data-attack-toggle="${iid}">⚔️ Angreifen ${open ? '▴' : '▾'}</button>${menu}`;
}

export function cardActionButtons(cardActions, attack) {
  if (!cardActions || !cardActions.length) return '';
  const buttons = [];
  for (const a of cardActions) {
    if (a.type === 'play_land') {
      buttons.push(
        actionButton(
          { type: 'play_land', instance_id: a.instance_id, name: a.name, face: a.face },
          t('bd.cast.playLand', { face: faceHint(a) })
        )
      );
    } else if (a.type === 'cast_spell' && a.locked && (!a.kicker_variant || a.kicker_variant.locked)) {
      const reason = a.lock_reason || t('bd.cast.noValidTarget');
      buttons.push(
        `<button type="button" class="gf-card-action gf-locked" disabled title="${escapeAttr(reason)}">🔒 ${escapeHtml(reason)}${faceHint(a)}</button>`
      );
    } else if (a.type === 'cast_spell' && (a.requires_target || a.kicker_variant || a.damage_divisions?.length || a.graveyard_exile_cost || a.sacrifice_count_cost || a.reveal_cost)) {
      buttons.push(castTargetHtml(a));
    } else if (a.type === 'cast_spell' && a.discard_cost) {
      // "As an additional cost to cast this spell, discard N cards" (RULE
      // 601.2b) — open the picker so the player chooses which cards pay it
      // (RULE 602.1), instead of the engine auto-discarding from the back
      // of the hand.
      const startInfo = JSON.stringify({
        iid: a.instance_id, face: a.face, mode: a.mode,
        warp: a.warp, evoke: a.evoke, surge: a.surge, blitz: a.blitz, pay_additional: a.pay_additional, bargained: a.bargained,
        gift_opponent_id: a.gift_opponent_id, splice_ids: a.splice_ids, free: !!a.free,
      });
      buttons.push(
        `${replicateFieldsHtml(a)}<button type="button" class="gf-card-action" data-discard-choice-start='${escapeAttr(startInfo)}'>${renderOracleText(t(a.blitz != null ? 'bd.cast.blitzPlain' : a.surge ? 'bd.cast.surgePlain' : a.evoke ? 'bd.cast.evokePlain' : 'bd.cast.castPlain', { mode: a.warp ? `${modeHint(a)} Warp (${a.warp_cost_label || a.cost_label})` : a.blitz != null ? `${modeHint(a)} (${a.blitz_cost_label || a.cost_label})` : modeHint(a), hint: giftHint(a), face: faceHint(a) }))}</button>`
      );
    } else if (a.type === 'cast_spell' && (a.has_x || a.has_kicker || a.replicate_costs?.length)) {
      const xField = a.has_x
        ? `<input type="number" min="${a.min_x || 0}" max="${a.max_x}" value="${a.max_x}" data-x-input="${xKey(a.instance_id, a.face, a.blitz, a.splice_ids)}" />`
        : '';
      const suffix = [
        a.has_x ? 'X' : null,
        a.replicate_costs?.length ? 'Replicate' : null,
        a.splice_ids?.length ? `Splice (${(a.splice_names || []).join(', ')})` : null,
        a.has_kicker ? (a.kicker_keyword === 'offspring' ? 'Offspring' : 'Kicker') : null,
        a.pay_additional ? a.additional_cost_label || 'Zusatzkosten' : null,
        a.bargained ? 'Bargain' : null,
        a.gift_opponent_id ? t('bd.cast.giftSuffix', { name: a.gift_opponent_name || a.gift_opponent_id }) : null,
      ].filter(Boolean).join(', ');
      buttons.push(`
        <div class="gf-cast-x">
          ${xField}${kickerFieldHtml(a)}${replicateFieldsHtml(a)}
          <button type="button" class="gf-card-action" data-cast-x='${escapeAttr(JSON.stringify({ iid: a.instance_id, face: a.face, mode: a.mode, entwine: a.entwine, alt_cost: !!a.alt_cost, warp: a.warp, evoke: a.evoke, surge: a.surge, blitz: a.blitz, pay_additional: a.pay_additional, bargained: a.bargained, gift_opponent_id: a.gift_opponent_id, splice_ids: a.splice_ids, free: !!a.free }))}'>${renderOracleText(t(a.blitz != null ? 'bd.cast.blitzSuffix' : a.surge ? 'bd.cast.surgeSuffix' : a.evoke ? 'bd.cast.evokeSuffix' : 'bd.cast.castSuffix', { suffix, mode: a.warp ? `${modeHint(a)} Warp (${a.warp_cost_label || a.cost_label})` : a.blitz != null ? `${modeHint(a)} (${a.blitz_cost_label || a.cost_label})` : modeHint(a), face: faceHint(a) }))}</button>
        </div>
      `);
    } else if (a.type === 'cast_spell') {
      const hint = a.base_cost && a.effective_cost && a.base_cost !== a.effective_cost
        ? ` 💰${escapeHtml(a.effective_cost)}`
        : '';
      buttons.push(
        actionButton(
          { type: 'cast_spell', instance_id: a.instance_id, name: a.name, face: a.face, mode: a.mode, entwine: a.entwine, alt_cost: !!a.alt_cost, warp: a.warp, evoke: a.evoke, surge: a.surge, blitz: a.blitz, pay_additional: a.pay_additional, bargained: a.bargained, gift_opponent_id: a.gift_opponent_id, splice_ids: a.splice_ids, free: !!a.free },
          t(a.blitz != null ? 'bd.cast.blitzPlain' : a.surge ? 'bd.cast.surgePlain' : a.evoke ? 'bd.cast.evokePlain' : 'bd.cast.castPlain', {
            mode: a.warp ? `${modeHint(a)} Warp (${a.warp_cost_label || a.cost_label})` : a.blitz != null ? `${modeHint(a)} (${a.blitz_cost_label || a.cost_label})` : modeHint(a),
            hint: `${hint}${a.pay_additional ? ` + ${a.additional_cost_label || 'Zusatzkosten'}` : ''}${a.bargained ? ' + Bargain' : ''}${giftHint(a)}`,
            face: faceHint(a),
          })
        )
      );
    } else if (a.type === 'plot') {
      buttons.push(actionButton({ type: 'plot', instance_id: a.instance_id },
        `Plot (${renderOracleText(a.cost_label)})`));
    } else if (a.type === 'suspend') {
      const label = `⏳ Suspend (${renderOracleText(a.cost_label || '')})`;
      if (a.has_x) {
        // Suspend announces its own X, independently of casting this card.
        buttons.push(`
          <div class="gf-cast-x">
            <input type="number" min="${escapeAttr(a.min_x)}" max="${escapeAttr(a.max_x)}" value="${escapeAttr(a.max_x)}" aria-label="Suspend X" data-x-input="${escapeAttr(xKey(a.instance_id, 'suspend'))}" />
            <button type="button" class="gf-card-action" data-suspend-x="${escapeAttr(a.instance_id)}">${label} (X)</button>
          </div>
        `);
      } else {
        buttons.push(actionButton({ type: 'suspend', instance_id: a.instance_id }, label));
      }
    } else if (a.type === 'activate_ability' && a.locked) {
      const reason = a.lock_reason || t('bd.cast.noValidTarget');
      buttons.push(
        `<button type="button" class="gf-card-action gf-locked" disabled title="${escapeAttr(reason)}">🔒 ${modeHint(a)} ${escapeHtml(reason)}</button>`
      );
    } else if (a.type === 'activate_ability' && (a.requires_target || a.return_cost || ((a.graveyard_exile_cost || a.reveal_cost) && !a.has_x))) {
      // BUG-53: "Exile N cards from your graveyard" -- the pool picker runs after targets (finishCastIfReady).
      buttons.push(castTargetHtml(a));
    } else if (a.type === 'activate_ability' && a.has_x) {
      buttons.push(`
        <div class="gf-cast-x">
          <input type="number" min="${a.min_x || 0}" max="${a.max_x}" value="${a.max_x}" data-x-input="${a.instance_id}" />
          <button type="button" class="gf-card-action${loyaltyModifierClass(a.cost_label)}" data-activate-x='${escapeAttr(JSON.stringify({ iid: a.instance_id, ability_index: a.ability_index, mode: a.mode }))}'>⚡ ${renderOracleText(a.cost_label || 'Aktivieren')} (X)${modeHint(a)}</button>
        </div>
      `);
    } else if (a.type === 'activate_ability' && a.power_tap_cost) {
      const info = JSON.stringify({ type: 'activate_ability', instance_id: a.instance_id, ability_index: a.ability_index });
      buttons.push(`<button type="button" class="gf-card-action" data-power-tap-start='${escapeAttr(info)}'>⚡ ${renderOracleText(a.cost_label)}</button>`);
    } else if (a.type === 'activate_ability' && (a.tap_cost || a.exile_cost)) {
      // Cost includes "tap N untapped <type>s you control" (RULE 602.1) —
      // which ones is the player's own choice, not an engine auto-pick.
      const startInfo = JSON.stringify({ iid: a.instance_id, type: 'activate_ability', ability_index: a.ability_index, mode: a.mode });
      buttons.push(
        `<button type="button" class="gf-card-action${loyaltyModifierClass(a.cost_label)}" data-tap-choice-start='${escapeAttr(startInfo)}'>⚡ ${renderOracleText(a.cost_label || 'Aktivieren')}${modeHint(a)}</button>`
      );
    } else if (a.type === 'activate_ability' && a.counter_cost) {
      // PAR-247: "Remove a counter from a permanent you control" -- the picker asks for the holder and kind.
      const startInfo = JSON.stringify({ iid: a.instance_id, ability_index: a.ability_index, mode: a.mode });
      buttons.push(
        `<button type="button" class="gf-card-action${loyaltyModifierClass(a.cost_label)}" data-counter-choice-start='${escapeAttr(startInfo)}'>⚡ ${renderOracleText(a.cost_label || 'Aktivieren')}${modeHint(a)}</button>`
      );
    } else if (a.type === 'activate_ability' && a.discard_cost) {
      // Cost includes "Discard a <type> card" (RULE 602.2b) — which cards pay it is the player's own choice.
      const startInfo = JSON.stringify({ iid: a.instance_id, type: 'activate_ability', ability_index: a.ability_index, mode: a.mode });
      buttons.push(
        `<button type="button" class="gf-card-action${loyaltyModifierClass(a.cost_label)}" data-discard-activate-start='${escapeAttr(startInfo)}'>⚡ ${renderOracleText(a.cost_label || 'Aktivieren')}${modeHint(a)}</button>`
      );
    } else if (a.type === 'activate_ability' && a.sacrifice_cost) {
      // Cost includes "Sacrifice a <type>" (RULE 602.1) — which permanent
      // pays it is the player's own choice, not an engine auto-pick.
      const startInfo = JSON.stringify({ iid: a.instance_id, type: 'activate_ability', ability_index: a.ability_index, mode: a.mode });
      buttons.push(
        `<button type="button" class="gf-card-action${loyaltyModifierClass(a.cost_label)}" data-sacrifice-choice-start='${escapeAttr(startInfo)}'>⚡ ${renderOracleText(a.cost_label || 'Aktivieren')}${modeHint(a)}</button>`
      );
    } else if (a.type === 'activate_ability') {
      buttons.push(
        actionButton(
          { type: 'activate_ability', instance_id: a.instance_id, ability_index: a.ability_index, mode: a.mode, name: a.name },
          `⚡ ${renderOracleText(a.cost_label || 'Aktivieren')}${modeHint(a)}`,
          loyaltyModifierClass(a.cost_label)
        )
      );
    } else if (a.type === 'tap_for_mana') {
      const optsList = a.options || [{ index: 0, label: '⟳' }];
      // A mana ability whose cost is more than tapping itself (Selvala's
      // {G}, Gnarlroot Trapper's life payment, Birchlore Rangers' "tap two
      // other Elves") shows its full cost instead of a bare "Tappen".
      const extraCost = a.cost_label && a.cost_label !== '{T}';
      if (a.has_x) {
        // ENG-51: "Sacrifice X Goats: Add X mana of any one color"
        // (Springjack Pasture) — X is announced with the activation.
        if (optsList.length > 1) {
          buttons.push(manaChoiceControlHtml(
            a, optsList, 'tap_for_mana',
            `${renderOracleText(a.cost_label || '{T}')} → X`,
            { hasX: true },
          ));
        } else {
          const colorButtons = optsList.map((opt) => {
            const info = JSON.stringify({ iid: a.instance_id, ability_index: a.ability_index, option_index: opt.index });
            return `<button type="button" class="gf-card-action" data-tap-x='${escapeAttr(info)}'>⟳ ${renderOracleText(a.cost_label || '')} → X·${escapeHtml(opt.label || '⟳')}</button>`;
          }).join('');
          buttons.push(`
            <div class="gf-cast-x">
              <input type="number" min="${a.min_x || 0}" max="${a.max_x}" value="${a.max_x}" data-x-input="${a.instance_id}" />
              ${colorButtons}
            </div>
          `);
        }
        if (a.any_combination) buttons.push(colorSplitHtml(a, 'tap_for_mana'));
        continue;
      }
      if (optsList.length > 1) {
        const text = extraCost
          ? `${renderOracleText(a.cost_label)} →`
          : '⟳ Tappen';
        buttons.push(manaChoiceControlHtml(
          a, optsList, 'tap_for_mana', text,
          { sacrificeCost: Boolean(a.sacrifice_cost) },
        ));
      } else {
        for (const opt of optsList) {
          const glyph = escapeHtml(manaOptionLabel(opt));
          const text = extraCost
            ? `${renderOracleText(a.cost_label)} → ${glyph}`
            : '⟳ Tappen';
          if (a.tap_cost) {
            // Which Elves pay the "tap N" part is the player's own choice
            // (RULE 602.1) — open the picker instead of sending right away.
            const startInfo = JSON.stringify({
              iid: a.instance_id, type: 'tap_for_mana',
              ability_index: a.ability_index, option_index: opt.index,
            });
            buttons.push(
              `<button type="button" class="gf-card-action" data-tap-choice-start='${escapeAttr(startInfo)}'>${text}</button>`
            );
          } else if (a.sacrifice_cost) {
            // A "Sacrifice a <type>: Add …" mana ability (Ashnod's Altar-
            // shaped) — same cost choice as `tap_cost` above, just naming
            // what to sacrifice instead of what to tap.
            const startInfo = JSON.stringify({
              iid: a.instance_id, type: 'tap_for_mana',
              ability_index: a.ability_index, option_index: opt.index,
            });
            buttons.push(
              `<button type="button" class="gf-card-action" data-sacrifice-choice-start='${escapeAttr(startInfo)}'>${text}</button>`
            );
          } else {
            buttons.push(
              actionButton(
                { type: 'tap_for_mana', instance_id: a.instance_id, option_index: opt.index, ability_index: a.ability_index,
                  ...(opt.cost_land ? { cost_land: opt.cost_land } : {}) },
                text
              )
            );
          }
        }
      }
      // RULE 605.1a "any combination of colours" (Flamebraider/Gwenna/
      // Smokebraider/Selvala) — an additional split-across-colours option
      // alongside the single-colour choice above (still legal, just less
      // flexible).
      if (a.any_combination) buttons.push(colorSplitHtml(a, 'tap_for_mana'));
    } else if (a.type === 'activate_hand_mana') {
      // RULE 605.1a "Exile this card from your hand: Add …" (Elvish/Simian
      // Spirit Guide) — the hand-zone counterpart of `tap_for_mana` above;
      // the cost is exiling the card itself, so there's no tap/summoning-
      // sickness framing to the button.
      const optsList = a.options || [{ index: 0, label: '⟳' }];
      if (optsList.length > 1) {
        buttons.push(manaChoiceControlHtml(
          a, optsList, 'activate_hand_mana',
          `📤 ${renderOracleText(a.cost_label || 'Exilieren')} →`,
        ));
      } else {
        for (const opt of optsList) {
          const glyph = opt.label || '⟳';
          const text = `📤 ${renderOracleText(a.cost_label || 'Exilieren')} → ${glyph}`;
          buttons.push(
            actionButton(
              { type: 'activate_hand_mana', instance_id: a.instance_id, option_index: opt.index, ability_index: a.ability_index },
              text
            )
          );
        }
      }
      if (a.any_combination) buttons.push(colorSplitHtml(a, 'activate_hand_mana'));
    } else if (a.type === 'set_skip_untap') {
      // RULE 502.1 "you may choose not to untap ~ during your untap step"
      // (Rubinia Soulsinger/Hivis of the Scale/The Pandorica-shaped) — a
      // sticky preference toggle (`GameObject.skip_untap`), not a one-off
      // action, so the button just flips it and reflects the current state.
      const on = a.skip_untap;
      buttons.push(
        actionButton(
          { type: 'set_skip_untap', instance_id: a.instance_id, value: !on },
          on ? '🔓 Wieder normal enttappen' : '🔒 Nicht enttappen lassen',
          on ? ' gf-card-action--skip-untap-on' : ''
        )
      );
    } else if (a.type === 'turn_face_up') {
      // RULE 116.2b: the special action of turning a face-down permanent
      // face up — one button per payable route (its morph/disguise cost,
      // or a manifested/cloaked creature card's own mana cost, RULE
      // 702.37e/702.168d/701.40b/701.58b). No stack, so the card is simply
      // revealed the moment this lands.
      buttons.push(
        actionButton(
          { type: 'turn_face_up', instance_id: a.instance_id, option_index: a.option_index },
          `🔎 Aufdecken (${renderOracleText(a.cost_label || '')})`
        )
      );
    } else if (a.type === 'unlock_door') {
      // RULE 709.5e/116.2m: a Room's special action — pay a locked half's mana cost to unlock it (main phase,
      // empty stack). No stack, so the half's text is live the moment this lands.
      buttons.push(
        actionButton(
          { type: 'unlock_door', instance_id: a.instance_id, door: a.door },
          `🚪 ${renderOracleText(t('bd.action.unlockDoor', { door: a.door_name || a.door, cost: a.cost_label || '' }))}`
        )
      );
    } else if (a.type === 'attack') {
      buttons.push(attackControlHtml(a, attack));
    }
  }
  return buttons.length ? `<div class="gf-card-actions">${buttons.join('')}</div>` : '';
}
