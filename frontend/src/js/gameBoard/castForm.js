// Pure helpers for cast/activation forms: X/kicker/replicate field keys and markup, target payloads (no board state).

import { renderOracleText } from '../cardTile.js';
import { t } from '../i18n.js';
import { escapeAttr, escapeHtml } from './html.js';

// A single requirement with `count > 1` (RULE 115.1a generalized to N>=2 —
// "destroy two target creatures"/"up to two target artifacts") is expanded
// into `count` synthetic one-per-round requirements sharing the same
// options, reusing the exact same "pick N from one pool, one at a time"
// modal + `excludePicked` de-dup a "tap N untapped <type>s you control"
// cost choice already uses (`data-tap-choice-start` below) — an optional
// requirement's existing per-round "∅ Kein Ziel" decline button then
// doubles as "stop after fewer than N", giving "up to N" for free.
//
// `distinct_controllers` (Run Away Together/Protector of the Wastes-
// shaped "N target creatures controlled by different players") is the one
// cross-target constraint modeled so far (`targeting.TargetSpec.
// distinct_controllers`) — `excludeControllers` mirrors `excludePicked`
// exactly, just keyed on an already-picked round's `controller_id`
// instead of its `instance_id`, so a later round's pool drops every
// permanent sharing a controller with anything already chosen.
//
// `owners` maps each expanded round back to the index of the requirement
// it came from, so the picks can be regrouped into `target_groups` — one
// list per *requirement*, in printed order — for the server (RULE 115.1,
// `StackItem.target_groups`). A flat list alone can't say which slot a
// declined "up to one" left empty, which is exactly what a spell like
// Epic Confrontation ("target creature you control gets +1/+2 …. It
// fights target creature you don't control.") needs to get right: pump
// and fight must land on *different* creatures.
//
// ENG-30: a `count_max` requirement ("N or M target X", a genuine RULE
// 601.2c range rather than "up to M") expands to `count_max` rounds
// instead of `count` — but only the rounds past the printed minimum
// (`count`) get the decline button (`castTargetModalHtml`'s `req.optional`
// read), so a per-round *clone* with its own `optional` is pushed instead
// of reusing one shared `req` reference the way every other requirement
// here still does.
export function expandMultiTargetRequirements(requirements, x = 0) {
  const expanded = [];
  const owners = [];
  let excludePicked = false;
  let excludeControllers = false;
  for (const [reqIndex, originalReq] of requirements.entries()) {
    const req = originalReq.mana_value_from_x
      ? { ...originalReq, options: (originalReq.options || []).filter((option) => Number(option.mana_value) === Number(x)) }
      : originalReq;
    const minimum = req.count_from_x ? x * req.count_from_x : (req.count ?? 1);
    const total = req.any_number ? (req.count_max || 0) : (req.count_max || minimum);
    if (total > 1) excludePicked = true;
    if (req.distinct_controllers) excludeControllers = true;
    for (let i = 0; i < total; i += 1) {
      expanded.push(
        req.count_max ? { ...req, optional: i >= minimum } : req
      );
      owners.push(reqIndex);
    }
  }
  return {
    requirements: expanded,
    owners,
    groupCount: requirements.length,
    excludePicked,
    excludeControllers,
  };
}

export function findTargetOptionForAction(action, instanceId, playerId) {
  if (!Array.isArray(action.targets)) return null;
  for (const req of action.targets) {
    if (!Array.isArray(req.options)) continue;
    for (const option of req.options) {
      if ((instanceId != null && String(option.instance_id) === instanceId) || (playerId != null && String(option.player_id) === playerId)) {
        return option;
      }
    }
  }
  return null;
}

export function resolvedDamageDivisions(divisions, x) {
  return divisions?.map((division) => division.total_from_x == null ? division
    : { ...division, total: x * division.total_from_x });
}

export function targetOptionPayload(o) {
  if (o.player_id != null) return { player_id: o.player_id };
  // PAR-247: a counter-cost option is a (permanent, counter kind) pair -- the kind rides along with the pick.
  return o.counter_kind != null ? { instance_id: o.instance_id, counter_kind: o.counter_kind } : { instance_id: o.instance_id };
}

// A defender spec from `legal_defenders_for` → the payload `declare_
// attackers` validates against. The two permanent kinds (planeswalker,
// RULE 508.1a; battle, RULE 310.5) are keyed by instance_id, a player by
// id — so branch on *which key the spec carries* rather than listing the
// permanent kinds, which is what silently mis-sent a battle as a player
// when the "battle" kind was added server-side.
export function defenderPayload(d) {
  return d.instance_id != null
    ? { kind: d.kind, instance_id: d.instance_id }
    : { kind: 'player', id: d.id };
}

// Cost picks `finishCastIfReady` opens a picker for after targets are chosen
// (RULE 601.2b / 602.2b): a drop-shortcut must not bypass them and let the
// engine auto-pick. Activations only open sacrifice/discard/reveal/counter pickers.
export function actionHasCostPick(action) {
  if (action.graveyard_exile_cost || action.tap_cost || action.return_cost || action.power_tap_cost) return true;
  return action.type === 'activate_ability'
    && Boolean(action.sacrifice_cost || action.discard_cost || action.reveal_cost || action.counter_cost);
}

// Modal-DFC (RULE 712.10) actions for the same card differ only by
// `face` — key any face-scoped DOM lookup on `instance_id:face` so a
// card offering both faces at once (e.g. both `has_x`) doesn't collide
// on a bare instance_id. Blitz instances also get separate X inputs.
export function xKey(instanceId, face, blitz, spliceIds) {
  const key = face ? `${instanceId}:${face}` : String(instanceId);
  const paymentKey = blitz != null ? `${key}:blitz:${blitz}` : key;
  return spliceIds?.length ? `${paymentKey}:splice:${spliceIds.join('_')}` : paymentKey;
}

// Kicker/Multikicker (RULE 702.33): same face-scoped keying as `xKey`, and
// the same "read the adjacent input at click time" idiom as `x`.
export function kickerKey(instanceId, face, spliceIds) {
  return xKey(instanceId, face, null, spliceIds);
}

// Kicker/Multikicker (RULE 702.33): a value input the same shape as an
// {X} spell's `has_x`/`max_x` field — 0/1 for a plain Kicker, 0..N for
// Multikicker (`a.max_kicker`); defaults to 0 (unkicked) rather than the
// max, unlike X, since paying it is an optional cost increase the player
// should opt into rather than pay by default.
export function kickerFieldHtml(a) {
  if (!a.has_kicker) return '';
  // RULE 702.33b/d (ENG-62): "Kicker A and/or B" has two separate costs, each payable once in any combination, so the
  // field is one toggle per cost (sent as a list of cost indices) instead of a count. A cost no affordable
  // combination includes is disabled.
  if (a.kicker_costs?.length > 1) {
    const key = kickerKey(a.instance_id, a.face, a.splice_ids);
    const options = a.kicker_options || [];
    const boxes = a.kicker_costs.map((cost, index) => {
      const affordable = options.some((combo) => combo.includes(index));
      return `<label class="gf-kicker-cost" title="${escapeAttr(`Kicker ${cost}`)}"><input type="checkbox" data-kicker-cost-input="${key}" data-cost-index="${index}"${affordable ? '' : ' disabled'} /> Kicker ${escapeHtml(cost)}</label>`;
    }).join('');
    return boxes + kickerXFieldHtml(a);
  }
  const label = a.kicker_keyword === 'offspring' ? 'Offspring' : 'Kicker';
  const title = a.kicker_cost ? `${label} ${a.kicker_cost}` : label;
  const field = `<input type="number" min="0" max="${a.max_kicker}" value="0" title="${escapeAttr(title)}" data-kicker-input="${kickerKey(a.instance_id, a.face, a.splice_ids)}" />`;
  return field + kickerXFieldHtml(a);
}

// Kicker's own {X} (RULE 702.33b, PAR-7 — Emblazoned Golem's "Kicker {X}",
// a separately-announced value from both the spell's own X and how many
// times Kicker is paid); defaults to 0 like Kicker itself, for the same
// "an optional cost increase, not paid by default" reason.
export function kickerXFieldHtml(a) {
  if (!a.kicker_has_x) return '';
  return `<input type="number" min="0" max="${a.kicker_max_x}" value="0" title="Kicker X" data-kicker-x-input="${kickerKey(a.instance_id, a.face, a.splice_ids)}" />`;
}

export function replicateFieldsHtml(a) {
  if (!a.replicate_costs?.length) return '';
  const fields = a.replicate_costs.map((cost, index) => {
    const title = `Replicate ${cost}${a.replicate_costs.length > 1 ? ` (${index + 1})` : ''}`;
    return `<label>${renderOracleText(title)} <input type="number" min="0" step="1" value="0" aria-label="${escapeAttr(title)}" data-replicate-input="${index}" /></label>`;
  }).join('');
  return `<span data-replicate-group="${escapeAttr(kickerKey(a.instance_id, a.face, a.splice_ids))}">${fields}</span>`;
}

export function powerTapTotal(ct) {
  return ct.targets.reduce((sum, target) => sum + (ct.powerTapOptions.find((option) => option.instance_id === target.instance_id)?.power || 0), 0);
}

export function actionButton(action, label, extraClass = '') {
  return `<button type="button" class="gf-card-action${extraClass}" data-action='${escapeAttr(JSON.stringify(action))}'>${label}</button>`;
}

export function manaOptionLabel(option) {
  const label = option.label || '⟳';
  return option.cost_land_name
    ? t('bd.mana.untapLandForMana', { mana: label, land: option.cost_land_name })
    : label;
}
