"""Effect-specific parameter utility shared by announcement and resolution."""
from __future__ import annotations
from .counters import proliferate_choice
import re
from .context import W, LOW_HAND, DEVELOPMENT_SOURCES, number, stable
from .profile import roles_for

MAX_DEATH_PAYOFFS = 3  # saturate speculative triggers rather than stack unlimited votes


def sacrifice_value(ctx, obj, text):
    """Net payoff; losing a permanent isn't intrinsically always bad."""
    obj = ctx.obj(obj)
    power, toughness = max(0, number(obj.get('power'))), max(0, number(obj.get('toughness')))
    gain = 0.0
    if 'power' in text:
        gain += power * (W.draw if 'draw' in text else W.body * 2)
    if 'toughness' in text:
        gain += toughness * (W.draw if 'draw' in text else W.body * 2)
        if 'discard' in text and 'power' in text:
            gain -= power * W.draw
    death_payoffs = sum('death-payoff' in ctx.roles(o) for o in ctx.ours)
    gain += min(death_payoffs, MAX_DEATH_PAYOFFS) * W.synergy
    if 'return' in ctx.text(obj) and 'graveyard' in ctx.text(obj):
        gain += W.engine
    return gain - ctx.value(obj)


def discard_value(ctx, obj):
    obj = ctx.obj(obj)
    value = -ctx.value(obj)
    roles = ctx.roles(obj)
    if 'graveyard' in roles or any('reanimate' in ctx.roles(o) for o in ctx.hand + ctx.ours):
        value += ctx.styles.get('graveyard', 0) * (number(obj.get('mana_value')) + W.engine)
    lands = sum(o.get('is_land', False) for o in ctx.hand)
    if obj.get('is_land') and lands + ctx.sources > DEVELOPMENT_SOURCES:
        value += W.engine
    return value


def target_value(ctx, option, text='', polarity=None):
    owner = ctx.owner(option)
    own = owner == ctx.player_id
    obj = ctx.obj(option)
    if option.get('player_id'):
        player = next((p for p in ctx.players if p['id'] == option['player_id']), {})
        gain = W.card if own == (polarity == 'beneficial') else -W.card
        if 'damage' in text or 'loses' in text:
            gain += (W.card - number(player.get('life'), 40)) if not own else -W.protection
        if 'draw' in text and not own:
            gain -= W.draw
        return gain
    value = ctx.value(obj)
    # Effect context can override polarity: sacrifice/transform is an input,
    # not a benefit to the most expensive permanent we control.
    if 'sacrifice' in text and own:
        return sacrifice_value(ctx, obj, text)
    if own and ('reveal cards' in text or 'reveal a' in text) and ('exile' in text or 'destroy' in text):
        return -value
    if 'goad' in text:
        return value if not own else -value
    if 'graveyard' in text and ('return' in text or 'put' in text):
        return value if own else -value
    if 'copy' in text:
        return value
    if ('exile' in text and 'return' in text) and own:
        return W.engine * bool('enters' in ctx.text(obj)) + value * .25
    if polarity == 'beneficial':
        gain = value if own else -value
        if own and 'counter' in text and 'alt-win' in ctx.roles(obj):
            # The goal's counter count belongs to this target, not to an
            # archetype label. Distinguish visible nearly-complete payoffs.
            gain += W.synergy * sum(number(n) for n in (obj.get('counters') or {}).values())
        if 'equip' in text or 'attach' in text or 'gets +' in text:
            gain += W.attack_trigger * bool('combat-hit' in ctx.roles(obj) or 'attack' in ctx.roles(obj))
        if obj.get('attacking'):
            gain += W.combat_damage * max(0, number(obj.get('power')))
        return gain
    return -value if own else value


def fill_costs(ctx, action):
    """Select only offered resources, respecting counts and target exclusions."""
    built = dict(action)
    text = ctx.effect_text(action)
    paid = set()
    for key, output in [('sacrifice_cost', 'sacrifice_choice'),
                        ('sacrifice_count_cost', 'sacrifice_choices'),
                        ('discard_cost', 'discard_choices'), ('tap_cost', 'tap_choices'),
                        ('exile_cost', 'hand_card_choices'), ('return_cost', 'return_choices')]:
        spec = action.get(key)
        if not spec:
            continue
        count = spec.get('count', 1)
        count = int(action.get('x', 0)) if str(count).casefold() == 'x' else int(count)
        options = [o for o in spec.get('options', []) if o.get('instance_id') not in paid]
        if key.startswith('sacrifice'):
            score = lambda o: sacrifice_value(ctx, o, text)
        elif key == 'discard_cost':
            score = lambda o: discard_value(ctx, o)
        else:
            score = lambda o: -ctx.value(o)
        chosen = sorted(options, key=lambda o: (-score(o), stable(o)))[:count]
        if len(chosen) != count:
            return None
        ids = [o['instance_id'] for o in chosen]
        if output == 'sacrifice_choice':
            built[output] = ids[0] if ids else None
        else:
            built[output] = ids
        paid.update(ids)
    # Crew has a power threshold rather than an exact count. Avoid tapping an
    # expensive future attacker if several disposable pilots can pay instead.
    if action.get('crew_cost'):
        spec = action['crew_cost']
        threshold = number(spec.get('power_required', spec.get('power', 0)))
        total, ids = 0, []
        for o in sorted(spec.get('options', []), key=lambda o: (ctx.value(o), stable(o))):
            total += number(o.get('crew_power', o.get('power', ctx.obj(o).get('power'))))
            ids.append(o['instance_id'])
            if total >= threshold:
                break
        if total < threshold:
            return None
        built['tap_choices'] = ids
    return built


def choice(ctx, answers):
    """None delegates wire-specific choices to the proven base handlers."""
    pending = ctx.view.get('pending_choice') or {}
    kind = pending.get('kind', '')
    options = [a for a in answers if a['type'] == 'choose']
    decline = next((a for a in answers if a['type'] == 'decline'), None)
    if not options:
        return decline
    if kind == 'proliferate':
        return proliferate_choice(ctx, options, decline)
    source = {'instance_id': pending.get('source_id', pending.get('source_instance_id')),
              'name': pending.get('source_name', '')}
    text = (pending.get('description') or ctx.text(source)).casefold()
    action = pending.get('action', '')
    if kind == 'search':
        def value(a):
            p = ctx.plan(a)
            if not p:
                return W.unknown
            gain = ctx.value(a)
            if 'land' in p.types:
                gain += W.land * (ctx.sources < DEVELOPMENT_SOURCES)
            # A missing ingredient earns a bounded vote only when another
            # ingredient is actually accessible, never from hidden libraries.
            board = {ctx.plan(o).name.casefold() for o in ctx.ours + ctx.hand if ctx.plan(o)}
            for combo in ctx.profile.combos:
                if p.name.casefold() in dict(combo.pieces) and len(set(dict(combo.pieces)) & board):
                    gain += W.combo_cap
            return gain
        return max(sorted(options, key=stable), key=value)
    if 'discard' in kind or action == 'discard':
        return max(sorted(options, key=stable), key=lambda a: discard_value(ctx, a))
    if kind == 'sacrifice' or action == 'sacrifice':
        return max(sorted(options, key=stable), key=lambda a: sacrifice_value(ctx, a, text))
    if kind in ('scry', 'surveil'):
        if pending.get('phase') == 'order':
            return max(sorted(options, key=stable), key=lambda a: ctx.value(a))
        # The engine's away phase offers each looked-at card; declining
        # retains the rest. Their names are authorized observations, not a
        # peek into the unoffered library.
        if pending.get('phase') == 'away':
            unwanted = []
            for a in options:
                p = ctx.plan(a)
                if p and ('land' in p.types and ctx.sources >= DEVELOPMENT_SOURCES
                          or kind == 'surveil' and 'graveyard' in p.roles):
                    unwanted.append(a)
            return min(unwanted, key=lambda a: (ctx.value(a), stable(a))) if unwanted else decline
    if kind in ('composite_optional', 'pay_cost_then', 'pay_energy_then') and not pending.get('entry_effect'):
        roles = roles_for(text)
        price = pending.get('cost_label', '')
        # Unknown optional payments retain conservative fallback. Known draw,
        # token and reanimation effects are actively accepted if affordable.
        energy_cost = str(price).casefold().count('{e}') or int(pending.get('energy_cost', 0) or 0)
        enough_energy = energy_cost <= number((ctx.me.get('counters') or {}).get('energy'))
        mana_cost = re.sub(r'\{e\}', '', str(price), flags=re.I)
        if roles & {'draw', 'tokens', 'reanimate', 'clones'} and enough_energy and (not mana_cost or ctx.payable(mana_cost)):
            pay = next((o for o in options if str(o.get('option_id')) in ('yes', 'pay', 'accept', '0')), None)
            return pay or options[0]
    if kind == 'choose_objects' and pending.get('minimum_card_types'):
        picked = [ctx.obj({'instance_id': i}) for i in pending.get('picked', [])]
        types = lambda o: set(re.findall(r'\b(?:artifact|creature|enchantment|instant|sorcery|land|planeswalker|battle|kindred)\b',
                                      ctx.obj(o).get('type_line', '').casefold()))
        have = set().union(*(types(o) for o in picked)) if picked else set()
        if len(have) >= int(pending['minimum_card_types']) and decline:
            return decline
        real = [a for a in options if a.get('instance_id') is not None]
        if real:
            # Diversify while retaining a strong selected reanimation target.
            return max(sorted(real,key=stable), key=lambda a: (len(types(a)-have), ctx.value(a)))
    if kind in ('choose_objects', 'target', 'choose_target'):
        objs = [a for a in options if a.get('instance_id') is not None or a.get('player_id')]
        if objs:
            return max(sorted(objs, key=stable), key=lambda a: target_value(ctx, a, text, pending.get('polarity')))
    return None
