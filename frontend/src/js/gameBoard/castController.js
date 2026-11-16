// Cast/activation targeting flow: the multi-step RULE 601.2c announcement (targets, X, kicker,
// costs) and the board interactions that drive it. A factory over `ctx` for the same reason as
// choices.js: `castTargeting` is reassigned as the flow advances, so it is read and written
// through the board's getter/setter context.

import { TARGET_CHOICE_KINDS } from './labels.js';
import { escapeAttr, escapeHtml } from './html.js';
import { expandMultiTargetRequirements, powerTapTotal, resolvedDamageDivisions, targetOptionPayload } from './castForm.js';
import { sameActivationMode } from './cardHints.js';
import { t } from '../i18n.js';

export function createCastController(ctx) {
  const {
    targetControllerChipHtml,
    act,
    persistCastTargetingDraft,
    readKicker,
    readKickerX,
    readReplicate,
    readX,
    render,
    requirementOwnerIndexForOption,
    selectedKickerAction,
    setStatus,
    submitManaActivation,
    wire,
  } = ctx;

  function finishCastIfReady() {
    if (!ctx.castTargeting) return;
    if (ctx.castTargeting.reqIndex < ctx.castTargeting.requirements.length) {
      persistCastTargetingDraft();
      render();
      return;
    }
    if (ctx.castTargeting.damageDivisions?.length && !ctx.castTargeting.allocatedDamage) {
      persistCastTargetingDraft();
      render();
      return;
    }
    const ct = ctx.castTargeting;
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
    if (!payload.tap_choices && action?.exile_value_cost) {
      const options = action.exile_value_cost.options;
      ctx.castTargeting = { instanceId: ct.instanceId, send: payload, x,
        requirements: Array.from({ length: options.length + 1 }, () => ({
          label: t('bd.cast.exileArtifactsValue'), options, optional: true,
        })), reqIndex: 0, targets: [], excludePicked: true, isTapChoice: true,
        isExileChoice: true, isExileValueChoice: true, exileValueRequired: payload.x ?? x ?? 0 };
      finishCastIfReady();
      return;
    }
    if (!payload.tap_choices && action?.power_tap_cost) {
      const cost = action.power_tap_cost;
      ctx.castTargeting = { instanceId: ct.instanceId, send: payload, x,
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
      ctx.castTargeting = { instanceId: ct.instanceId, send: payload, x,
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
      ctx.castTargeting = { instanceId: ct.instanceId, send: payload, x,
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
        ctx.castTargeting = { instanceId: ct.instanceId, send: payload, x,
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
      ctx.castTargeting = { instanceId: ct.instanceId, send: payload, x,
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
      ctx.castTargeting = { instanceId: ct.instanceId, send: payload, x, requirements, reqIndex: 0, targets: [],
        excludePicked: true, isSacrificeChoice: true, sacrificeSlots: Boolean(slots) };
      persistCastTargetingDraft();
      render();
      return;
    }
    if (send.type === 'activate_ability' && !isDiscardChoice && action?.discard_cost && !payload.discard_choices) {
      const { count, matching_names, different_names } = action.discard_cost;
      const options = action.discard_cost.options.filter((option) => !action.discard_cost.mana_value_equals_x || option.mana_value === (payload.x ?? x ?? 0));
      ctx.castTargeting = { instanceId: ct.instanceId, send: payload, x,
        requirements: Array.from({ length: count }, () => ({ label: t('bd.discard.card'), options, optional: false, matching_names, different_names })),
        reqIndex: 0, targets: [], excludePicked: true, isDiscardChoice: true };
      persistCastTargetingDraft();
      render();
      return;
    }
    // RULE 701.68: which creature pays a "Blight N" cost is the player's choice (one candidate needs no prompt).
    if (payload.blight_choice == null && action?.blight_cost?.options?.length > 1) {
      ctx.castTargeting = { instanceId: ct.instanceId, send: payload, x,
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
        ctx.castTargeting = { instanceId: ct.instanceId, send: payload, x,
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
      const { options } = action.graveyard_exile_cost;
      const count = action.graveyard_exile_cost.count === 'x' ? (payload.x ?? x ?? 0) : action.graveyard_exile_cost.count;
      if (count === 0) {
        ctx.castTargeting = { ...ct, send: payload, targets: [], requirements: [], reqIndex: 0, isGraveyardExileChoice: true };
        finishCastIfReady();
        return;
      }
      const eligible = action.graveyard_exile_cost.mana_value_equals_x
        ? options.filter(option => option.mana_value === (payload.x || 0)) : options;
      ctx.castTargeting = { instanceId: ct.instanceId, send: payload, x,
        requirements: Array.from({ length: count }, () => ({
          label: t('bd.exile.graveyardCostCard'), options: eligible, optional: false,
        })),
        reqIndex: 0, targets: [], excludePicked: true, isGraveyardExileChoice: true,
      };
      persistCastTargetingDraft();
      render();
      return;
    }
    ctx.castTargeting = null;
    act(payload);
    persistCastTargetingDraft();
  }

  // The candidates of the current RULE 115 target round, after the
  // per-round exclusions (same permanent twice, same controller twice).
  function castTargetOptions() {
    if (!ctx.castTargeting) return [];
    const req = ctx.castTargeting.requirements[ctx.castTargeting.reqIndex] || {};
    let options = req.options || [];
    if (req.max_mana_value_from_x) options = options.filter((option) => option.mana_value <= ctx.castTargeting.x);
    if (ctx.castTargeting.isExileValueChoice) {
      const picked = new Set(ctx.castTargeting.targets.map((target) => target.instance_id));
      const paid = ctx.castTargeting.targets.reduce((sum, target) => sum + (req.options.find((o) => o.instance_id === target.instance_id)?.mana_value || 0), 0);
      options = options.filter((candidate) => {
        if (picked.has(candidate.instance_id)) return false;
        const remaining = ctx.castTargeting.exileValueRequired - paid - candidate.mana_value;
        if (remaining < 0) return false;
        let sums = new Set([0]);
        for (const option of req.options) {
          if (picked.has(option.instance_id) || option.instance_id === candidate.instance_id) continue;
          sums = new Set([...sums, ...[...sums].map((value) => value + option.mana_value)]);
        }
        return sums.has(remaining);
      });
    }
    if (req.different_names) {
      const picked = ctx.castTargeting.targets.map((target) => req.options.find((option) => option.instance_id === target.instance_id));
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
        return extend(0, ctx.castTargeting.requirements.length - prefix.length, names);
      };
      options = options.filter((option) => completes([...picked, option]));
    }
    if (req.matching_names && ctx.castTargeting.targets.length) {
      const picked = ctx.castTargeting.targets.map((target) => req.options.find((option) => option.instance_id === target.instance_id));
      options = options.filter((option) => {
        let common = option.names || [];
        for (const prior of picked) common = common.filter((name) => prior?.names?.includes(name));
        return common.length > 0;
      });
    }
    if (req.shared_creature_type && ctx.castTargeting.targets.length) {
      const picked = ctx.castTargeting.targets.map((target) => req.options.find((option) => option.instance_id === target.instance_id));
      options = options.filter((option) => {
        let common = option.creature_types || [];
        for (const prior of picked) common = common.filter((kind) => prior?.creature_types?.includes(kind));
        return common.length > 0;
      });
    }
    if (req.shared_color && ctx.castTargeting.targets.length) {
      const picked = ctx.castTargeting.targets.map((target) => req.options.find((option) => option.instance_id === target.instance_id));
      options = options.filter((option) => {
        let common = option.colors || [];
        for (const prior of picked) common = common.filter((color) => prior?.colors?.includes(color));
        return common.length > 0;
      });
    }
    if (ctx.castTargeting.excludePicked || req.distinct_from_others) {
      // A "tap N untapped <type>s you control" cost (RULE 602.1): the same
      // permanent can't pay two of the N picks. `distinct_from_others` is
      // RULE 109.5's "**another** target creature" (Pit Fight, Ulvenwald
      // Tracker) — same exclusion, but across *requirements*: whatever the
      // other half of the clause already chose is off this round's pool.
      // A player option has a `player_id` and no `instance_id`, so the key names which of the two it is
      // (ENG-52: "any other target" can be a player; `undefined` must not exclude every player).
      const targetKey = (o) => (o.player_id != null ? `p:${o.player_id}` : `i:${o.instance_id}`);
      const pickedKeys = new Set(ctx.castTargeting.targets.map(targetKey));
      options = options.filter((o) => !pickedKeys.has(targetKey(o)));
    }
    if (ctx.castTargeting.excludeControllers) {
      // Run Away Together/Protector of the Wastes-shaped "controlled by
      // different players": once one round has picked a permanent, no
      // later round may pick another one sharing that controller.
      const pickedControllers = new Set((ctx.castTargeting.pickedControllers || []).filter((c) => c != null));
      options = options.filter((o) => !pickedControllers.has(o.controller_id));
    }
    if (req.same_graveyard) {
      const owner = ctx.castTargeting.owners?.[ctx.castTargeting.reqIndex];
      const picked = ctx.castTargeting.groups?.[owner] || [];
      const first = req.options.find((o) => o.instance_id === picked[0]?.instance_id);
      if (first) options = options.filter((o) => o.graveyard_owner_id === first.graveyard_owner_id);
    }
    for (const [field, limit] of [['power', req.total_power_max], ['mana_value', req.total_mana_value_max]]) {
      if (limit == null) continue;
      const owner = ctx.castTargeting.owners?.[ctx.castTargeting.reqIndex];
      const picked = ctx.castTargeting.groups?.[owner] || [];
      const used = picked.reduce((sum, target) => sum + (req.options.find((o) => o.instance_id === target.instance_id)?.[field] || 0), 0);
      options = options.filter((o) => used + (o[field] || 0) <= limit);
    }
    return options;
  }

  // One RULE 115 pick, whether it came from the popup button or a click on
  // the board (VIS-14). `target === null` is the "no target" decline.
  function pickCastTarget({ instance_id: iid, target, controller_id: controllerId }) {
    if (!ctx.castTargeting || ctx.castTargeting.instanceId !== iid) return;
    if (target !== null) {
      ctx.castTargeting.targets.push(target);
      // …and into this round's own requirement group, so a declined
      // "up to one" leaves an *empty* group rather than shifting every
      // later pick one slot up (see `expandMultiTargetRequirements`).
      const owner = ctx.castTargeting.owners?.[ctx.castTargeting.reqIndex];
      if (owner != null) ctx.castTargeting.groups?.[owner]?.push(target);
      // Tracked separately from `target` (the wire-format pick sent to
      // the server) purely for `excludeControllers`'s client-side
      // per-round filtering — see `castTargetOptions`.
      (ctx.castTargeting.pickedControllers ||= []).push(controllerId ?? null);
    }
    const requirement = ctx.castTargeting.requirements[ctx.castTargeting.reqIndex];
    if (target === null && requirement?.any_number) {
      const owner = ctx.castTargeting.owners[ctx.castTargeting.reqIndex];
      while (ctx.castTargeting.owners[ctx.castTargeting.reqIndex] === owner) ctx.castTargeting.reqIndex += 1;
      finishCastIfReady();
      return;
    }
    ctx.castTargeting.reqIndex = target === null && (ctx.castTargeting.isSacrificeCountChoice || ctx.castTargeting.isPowerTapChoice || ctx.castTargeting.isExileValueChoice)
      ? ctx.castTargeting.requirements.length : ctx.castTargeting.reqIndex + 1;
    finishCastIfReady();
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
    ctx.castTargeting = {
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
      ctx.castTargeting.targets.push(target);
      ctx.castTargeting.groups[owner].push(target);
      ctx.castTargeting.reqIndex = 1;
    }
    finishCastIfReady();
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
    return (ctx.view?.legal_actions || []).find(
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

  function castTargetModalHtml() {
    if (!ctx.castTargeting) return '';
    if (ctx.castTargeting.reqIndex >= ctx.castTargeting.requirements.length && ctx.castTargeting.damageDivisions?.length) return damageDivisionModalHtml();
    const iid = ctx.castTargeting.instanceId;
    const total = ctx.castTargeting.requirements.length;
    const idx = ctx.castTargeting.reqIndex;
    const req = ctx.castTargeting.requirements[idx] || {};
    const options = castTargetOptions();
    // A cost *choice* (RULE 602.1: tap N / sacrifice / discard for a cost),
    // not a RULE 115 target — different heading and glyph from "Ziel wählen".
    const isDiscardChoice = ctx.castTargeting.isDiscardChoice;
    const isCostChoice = ctx.castTargeting.isTapChoice || ctx.castTargeting.isSacrificeChoice || isDiscardChoice || ctx.castTargeting.isGraveyardExileChoice || ctx.castTargeting.isSacrificeCountChoice || ctx.castTargeting.isReturnChoice || ctx.castTargeting.isBlightChoice || ctx.castTargeting.isRevealChoice || ctx.castTargeting.isCounterChoice;
    const modalGlyph = ctx.castTargeting.isCounterChoice ? '🔢' : ctx.castTargeting.isRevealChoice ? '👁️' : ctx.castTargeting.isBlightChoice ? '🥀' : ctx.castTargeting.isReturnChoice ? '↩️' : (ctx.castTargeting.isGraveyardExileChoice || ctx.castTargeting.isExileChoice) ? '🌀' : isDiscardChoice ? '🗑️' : (ctx.castTargeting.isTapChoice ? '⟳' : ((ctx.castTargeting.isSacrificeChoice || ctx.castTargeting.isSacrificeCountChoice) ? '💀' : '🎯'));
    const buttons = options.map((o) => {
      const payload = JSON.stringify({
        instance_id: iid, target: targetOptionPayload(o), controller_id: o.controller_id ?? null,
      });
      const hover = o.instance_id != null ? ` data-hover-card="${escapeHtml(o.name || '')}"` : '';
      // VIS-13: who controls this candidate, so two same-named permanents
      // on different boards can be told apart.
      const name = ctx.castTargeting.isPowerTapChoice ? `${o.name} (${o.power})` : ctx.castTargeting.isExileValueChoice ? `${o.name} (${o.mana_value})` : o.name;
      return `<button type="button"${hover} data-cast-target-pick='${escapeAttr(payload)}'>${modalGlyph} ${escapeHtml(name)}${targetControllerChipHtml(o)}</button>`;
    });
    const exileValuePaid = ctx.castTargeting.isExileValueChoice
      ? ctx.castTargeting.targets.reduce((sum, target) => sum + (req.options.find((o) => o.instance_id === target.instance_id)?.mana_value || 0), 0) : 0;
    const exileValueComplete = !ctx.castTargeting.isExileValueChoice || (ctx.castTargeting.targets.length > 0 && exileValuePaid === ctx.castTargeting.exileValueRequired);
    if (req.optional && exileValueComplete && (!ctx.castTargeting.isPowerTapChoice || powerTapTotal(ctx.castTargeting) >= ctx.castTargeting.powerRequired)) {
      const skip = JSON.stringify({ instance_id: iid, target: null });
      buttons.push(`<button type="button" class="gf-decline" data-cast-target-pick='${escapeAttr(skip)}'>${t(ctx.castTargeting.isSacrificeCountChoice || ctx.castTargeting.isPowerTapChoice || ctx.castTargeting.isExileValueChoice ? 'bd.cast.finishCostChoice' : 'bd.cast.noTarget')}</button>`);
    }
    const heading = isCostChoice ? t('bd.cast.payCosts') : t('bd.cast.chooseTarget');
    const progress = ctx.castTargeting.isExileValueChoice
      ? t('bd.cast.exileValueProgress', { value: exileValuePaid, required: ctx.castTargeting.exileValueRequired })
      : ctx.castTargeting.isPowerTapChoice
      ? t('bd.cast.tapPowerProgress', { power: powerTapTotal(ctx.castTargeting), required: ctx.castTargeting.powerRequired })
      : total > 1 ? t('bd.cast.progress', { i: idx + 1, total }) : (isCostChoice ? t('bd.cast.select') : t('bd.cast.chooseTarget'));
    // VIS-14: only a real target round can be answered by clicking the
    // board; a cost choice (tap/sacrifice/discard) keeps the popup-only flow.
    const asideOffered = !isCostChoice;
    const aside = asideOffered && ctx.castTargetAside;
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

  function damageDivisionModalHtml() {
    const ct = ctx.castTargeting;
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

  function wireCastForms() {
    // {X} spells read the announced value from the adjacent number input at
    // click time rather than baking it into a static data-action attribute.
    ctx.root.querySelectorAll('[data-replicate-group] input').forEach((input) => {
      input.addEventListener('input', () => {
        const key = input.closest('[data-replicate-group]').dataset.replicateGroup;
        ctx.root.querySelectorAll(`[data-replicate-group="${key}"] [data-replicate-input="${input.dataset.replicateInput}"]`)
          .forEach((other) => { other.value = input.value; });
      });
    });

    ctx.root.querySelectorAll('[data-cast-x]').forEach((el) => {
      el.addEventListener('click', () => {
        const { iid, face, mode, entwine, warp, evoke, surge, blitz, pay_additional, bargained, gift_opponent_id, splice_ids, free, alt_cost } = JSON.parse(el.dataset.castX);
        const x = readX(iid, face, blitz, splice_ids);
        const kicked = readKicker(iid, face, splice_ids);
        const kicker_x = readKickerX(iid, face, splice_ids);
        act({ type: 'cast_spell', instance_id: iid, x, face, kicked, kicker_x, mode, entwine, warp, evoke, surge, blitz, pay_additional, bargained, gift_opponent_id, splice_ids, free, alt_cost });
      });
    });

    ctx.root.querySelectorAll('[data-suspend-x]').forEach((el) => {
      el.addEventListener('click', () => {
        const iid = Number(el.dataset.suspendX);
        act({ type: 'suspend', instance_id: iid, x: readX(iid, 'suspend') });
      });
    });

    ctx.root.querySelectorAll('[data-tap-x]').forEach((el) => {
      el.addEventListener('click', () => {
        const { iid, ability_index, option_index } = JSON.parse(el.dataset.tapX);
        submitManaActivation({ type: 'tap_for_mana', instance_id: iid, ability_index, option_index, x: readX(iid, null) });
      });
    });

    ctx.root.querySelectorAll('[data-mana-choice-activate]').forEach((el) => {
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

    ctx.root.querySelectorAll('[data-activate-x]').forEach((el) => {
      el.addEventListener('click', () => {
        const { iid, ability_index, mode } = JSON.parse(el.dataset.activateX);
        const x = readX(iid, null);
        const action = (ctx.view?.legal_actions || []).find(a => a.type === 'activate_ability'
          && a.instance_id === Number(iid) && a.ability_index === ability_index
          && sameActivationMode(a, mode));
        if (action?.graveyard_exile_cost) {
          prepareCastTargeting(action);
          return;
        }
        if (action?.reveal_cost || action?.counter_cost) {
          // PAR-247: an announced X that is paid with chosen cards (Martyr of Ashes) goes through the cost pickers.
          ctx.castTargeting = {
            instanceId: Number(iid), requirements: [], reqIndex: 0, targets: [], x,
            send: { type: 'activate_ability', instance_id: iid, ability_index, mode, x },
          };
          finishCastIfReady();
          return;
        }
        act({ type: 'activate_ability', instance_id: iid, ability_index, mode, x });
      });
    });

    ctx.root.querySelectorAll('[data-cast-target-start]').forEach((el) => {
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
        ctx.castTargeting = {
          instanceId: iid, requirements, owners, reqIndex: 0, targets: [], x, send,
          damageDivisions: resolvedDamageDivisions(action.damage_divisions, x), divisionRequirements: action.targets,
          groups: Array.from({ length: groupCount }, () => []),
          excludePicked, excludeControllers,
        };
        finishCastIfReady();
      });
    });

    ctx.root.querySelectorAll('[data-damage-requirement]').forEach((input) => {
      input.addEventListener('input', () => {
        if (!ctx.castTargeting) return;
        const index = input.dataset.damageRequirement;
        const inputs = [...ctx.root.querySelectorAll(`[data-damage-requirement="${index}"]`)];
        (ctx.castTargeting.damageDraft ||= {})[index] = inputs.map((field) => field.value);
        persistCastTargetingDraft();
      });
    });

    ctx.root.querySelector('[data-damage-confirm]')?.addEventListener('click', () => {
      const ct = ctx.castTargeting;
      if (!ct) return;
      const allocations = {};
      let valid = true;
      for (const division of ct.damageDivisions || []) {
        const index = division.requirement_index;
        const inputs = [...ctx.root.querySelectorAll(`[data-damage-requirement="${index}"]`)];
        const values = inputs.map((input) => input.value === '' ? NaN : Number(input.value));
        if (values.length !== (ct.groups?.[index] || []).length
            || values.some((value) => !Number.isInteger(value) || value < division.min_each)
            || (values.length > 0 && values.reduce((sum, value) => sum + value, 0) !== division.total)) valid = false;
        allocations[index] = values;
      }
      if (!valid) {
        ctx.root.querySelector('[data-damage-error]').textContent = 'Bitte den gesamten Schaden in ganzen Zahlen auf alle gewählten Ziele verteilen.';
        return;
      }
      ct.allocatedDamage = allocations;
      finishCastIfReady();
    });

    ctx.root.querySelectorAll('[data-cast-target-pick]').forEach((el) => {
      el.addEventListener('click', () => pickCastTarget(JSON.parse(el.dataset.castTargetPick)));
    });

    // VIS-14: push the target popup aside / bring it back.
    ctx.root.querySelector('[data-cast-target-aside]')?.addEventListener('click', () => {
      ctx.castTargetAside = !ctx.castTargetAside;
      render();
    });
    wirePickTargets();

    ctx.root.querySelectorAll('[data-cast-target-cancel]').forEach((el) => {
      el.addEventListener('click', () => {
        ctx.castTargeting = null;
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
    ctx.root.querySelectorAll('.gf-mana-split').forEach((container) => {
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

    ctx.root.querySelectorAll('[data-power-tap-start]').forEach((el) => {
      el.addEventListener('click', () => {
        const info = JSON.parse(el.dataset.powerTapStart);
        const action = ctx.view.legal_actions.find((a) => a.type === 'activate_ability'
          && a.instance_id === info.instance_id && a.ability_index === info.ability_index);
        if (action) prepareCastTargeting(action);
      });
    });

    ctx.root.querySelectorAll('[data-tap-choice-start]').forEach((el) => {
      el.addEventListener('click', () => {
        const info = JSON.parse(el.dataset.tapChoiceStart);
        const iid = Number(info.iid);
        const option_index = info.option_from_select
          ? Number(el.closest('.gf-mana-choice')?.querySelector('[data-mana-option]')?.value)
          : info.option_index;
        const action = (ctx.view?.legal_actions || []).find(
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
          label: action.exile_cost ? t(action.exile_cost.spell ? 'bd.exile.spell' : 'bd.exile.permanent') : action.tap_cost?.untap ? t('bd.untap.permanent') : 'zu tappende Kreatur', options, optional: false,
          shared_creature_type: action.tap_cost?.shared_creature_type,
        }));
        const send = info.type === 'activate_ability'
          ? { type: 'activate_ability', instance_id: iid, ability_index: info.ability_index, mode: info.mode }
          : { type: 'tap_for_mana', instance_id: iid, ability_index: info.ability_index, option_index };
        ctx.castTargeting = {
          instanceId: iid, requirements, reqIndex: 0, targets: [], x: 0, send,
          excludePicked: true, isTapChoice: true, isExileChoice: !!action.exile_cost,
        };
        finishCastIfReady();
      });
    });

    ctx.root.querySelectorAll('[data-sacrifice-choice-start]').forEach((el) => {
      el.addEventListener('click', () => {
        const info = JSON.parse(el.dataset.sacrificeChoiceStart);
        const iid = Number(info.iid);
        const option_index = info.option_from_select
          ? Number(el.closest('.gf-mana-choice')?.querySelector('[data-mana-option]')?.value)
          : info.option_index;
        const action = (ctx.view?.legal_actions || []).find(
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
        ctx.castTargeting = {
          instanceId: iid, requirements, reqIndex: 0, targets: [], x: 0, send,
          excludePicked: true, isSacrificeChoice: true, sacrificeSlots: Boolean(slots),
        };
        finishCastIfReady();
      });
    });

    ctx.root.querySelectorAll('[data-counter-choice-start]').forEach((el) => {
      el.addEventListener('click', () => {
        const info = JSON.parse(el.dataset.counterChoiceStart);
        const iid = Number(info.iid);
        ctx.castTargeting = {
          instanceId: iid, requirements: [], reqIndex: 0, targets: [], x: 0,
          send: { type: 'activate_ability', instance_id: iid, ability_index: info.ability_index, mode: info.mode },
        };
        finishCastIfReady();
      });
    });

    ctx.root.querySelectorAll('[data-discard-activate-start]').forEach((el) => {
      el.addEventListener('click', () => {
        const info = JSON.parse(el.dataset.discardActivateStart);
        const iid = Number(info.iid);
        const action = (ctx.view?.legal_actions || []).find(
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
        ctx.castTargeting = {
          instanceId: iid, requirements, reqIndex: 0, targets: [], x: 0,
          send: { type: 'activate_ability', instance_id: iid, ability_index: info.ability_index, mode: info.mode },
          excludePicked: true, isDiscardChoice: true,
        };
        finishCastIfReady();
      });
    });

    ctx.root.querySelectorAll('[data-discard-choice-start]').forEach((el) => {
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
        ctx.castTargeting = {
          instanceId: iid, requirements, reqIndex: 0, targets: [], x: 0, send,
          excludePicked: true, isDiscardChoice: true,
        };
        finishCastIfReady();
      });
    });
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
        el = ctx.root.querySelector(`[data-instance-id="${id}"] > .card`)
          || ctx.root.querySelector(`[data-stack-instance-id="${id}"] > .card`);
      } else if (pick.playerId != null) {
        const id = CSS.escape(String(pick.playerId));
        el = ctx.root.querySelector(`.gf-player-board[data-player-id="${id}"] .gf-player-board-head`)
          || ctx.root.querySelector(`.gf-opponent[data-player-id="${id}"]`);
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

  // VIS-14: what can be clicked on the board right now because the target
  // popup is pushed aside — `{instanceId | playerId, activate}` per legal
  // candidate. Covers both target UIs: the cast/activate picker and the
  // `trigger_target` pending choice. Cost choices (tap/sacrifice/discard)
  // are not targets and stay popup-only.
  function pickablesForBoard() {
    const out = [];
    if (ctx.castTargeting && ctx.castTargetAside && !ctx.castTargeting.isTapChoice
        && !ctx.castTargeting.isSacrificeChoice && !ctx.castTargeting.isDiscardChoice && !ctx.castTargeting.isReturnChoice && !ctx.castTargeting.isBlightChoice) {
      for (const o of castTargetOptions()) {
        const payload = { instance_id: ctx.castTargeting.instanceId, target: targetOptionPayload(o), controller_id: o.controller_id ?? null };
        out.push({ instanceId: o.instance_id, playerId: o.player_id, activate: () => pickCastTarget(payload) });
      }
    }
    const pending = ctx.view?.state?.pending_choice;
    if (pending && ctx.choiceAside && TARGET_CHOICE_KINDS.has(pending.kind)) {
      const players = new Set((ctx.view.state.players || []).map((pl) => pl.id));
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

  return {
    finishCastIfReady,
    wireCostPayments,
    pickablesForBoard,
    findTargetableAction,
    wireCastForms,
    prepareCastTargeting,
    castTargetModalHtml,
    wirePickTargets,
    pickCastTarget,
  };
}
