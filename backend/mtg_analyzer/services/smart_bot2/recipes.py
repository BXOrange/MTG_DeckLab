"""Mechanic operators. Spellbook ingredients alone never prove execution."""
from __future__ import annotations
from collections import Counter
import re
from .context import W, number
from .profile import roles_for


def library_trigger(ctx):
    for item in ctx.stack:
        if item.get('controller_id') == ctx.player_id and item.get('category') == 'triggered_ability':
            source = item.get('source') or {}
            if 'library-win' in ctx.roles(source):
                return True
    return False


def depleter(ctx, obj):
    text = ctx.text(obj)
    # Two explicit semantics, not names: an absent name can exhaust the
    # library, or repeat exiling unless duplicate names stop the process.
    return ('exile' in text and 'library' in text and (
        'named card' in text or 'two cards with the same name' in text))


def library_ready(ctx, action):
    """A coherent mana allocation and compatible empty-library operation."""
    plan = ctx.plan(action)
    if not plan:
        return False
    for obj in ctx.hand:
        if not depleter(ctx, obj):
            continue
        text = ctx.text(obj)
        if 'two cards with the same name' in text:
            outside = Counter(o.get('name', '').casefold() for o in ctx.objects if
                              o.get('owner_id', o.get('controller_id')) == ctx.player_id and not o.get('is_token'))
            if any(q - outside[n] > 1 for n, q in ctx.profile.quantities.items()):
                continue
        p = ctx.plan(obj)
        if p and ctx.payable(plan.cost, p.cost):
            return True
    return False


def naming_choice(ctx, answers):
    if not library_trigger(ctx):
        return None
    pending = ctx.view.get('pending_choice') or {}
    choices = [a for a in answers if a['type'] == 'choose']
    if pending.get('kind') == 'tainted_pact':
        return next((a for a in choices if a.get('option_id') == 'continue'), None)
    if pending.get('kind') != 'name_card':
        return None
    outside = Counter(o.get('name', '').casefold() for o in ctx.objects
                      if o.get('owner_id', o.get('controller_id')) == ctx.player_id and not o.get('is_token'))
    absent = [n for n, q in sorted(ctx.profile.quantities.items()) if outside[n] >= q]
    for name in absent:
        found = next((a for a in choices if (a.get('name') or '').casefold() == name), None)
        if found:
            return found
    free = next((a for a in choices if a.get('free_text')), None)
    if absent and free:
        return {**free, 'option_id': ctx.profile.cards[absent[0]].name}
    return None


def combo_progress(ctx, action):
    p = ctx.plan(action)
    if not p:
        return 0.0, 'none'
    board = Counter(o.get('name', '').casefold() for o in ctx.ours)
    accessible = board + Counter(o.get('name', '').casefold() for o in ctx.hand + ctx.me.get('command', []))
    votes, status = [], 'recognized'
    for combo in ctx.profile.combos:
        needed = dict(combo.pieces)
        if p.name.casefold() not in needed:
            continue
        progress = sum(min(board[n], q) for n, q in combo.pieces)
        reachable = all(accessible[n] >= q for n, q in combo.pieces)
        # No presence, no bonus merely for being in a saved pool match.
        vote = W.combo_cap * progress / max(1, sum(needed.values()))
        if reachable:
            vote = W.combo_cap
            status = 'reachable'
        if action.get('type') != 'activate_ability' and board[p.name.casefold()] >= needed[p.name.casefold()]:
            vote = 0
        votes.append(vote)
    return max(votes, default=0), status if votes else 'none'


def library_threshold(ctx, action):
    """Known devotion-based threshold; unknown X is conservatively zero."""
    text = ctx.text(action)
    colors = {'white':'W','blue':'U','black':'B','red':'R','green':'G'}
    match = re.search(r'your devotion to (white|blue|black|red|green)', text)
    if not match:
        return 0
    symbol = colors[match[1]]
    permanent_costs = [str(o.get('mana_cost') or (ctx.plan(o).cost if ctx.plan(o) else '')) for o in ctx.ours]
    plan = ctx.plan(action)
    if plan:
        permanent_costs.append(plan.cost)
    return sum(len(re.findall(r'\{[^}]*'+symbol+r'[^}]*\}',cost.upper())) for cost in permanent_costs)


def recipe_vote(ctx, action):
    text, roles = ctx.effect_text(action), roles_for(ctx.effect_text(action))
    status = 'none'
    if depleter(ctx, action):
        return (W.lethal, 'in_execution') if library_trigger(ctx) else (-W.lethal, 'not_startable')
    if 'library-win' in ctx.roles(action) and action.get('type') == 'cast_spell' and 'enters' in ctx.text(action):
        if number(ctx.me.get('library_count'), 99) <= library_threshold(ctx,action) or library_ready(ctx, action):
            return W.lethal, 'startable'
        return -W.lethal, 'not_startable'
    p = ctx.plan(action)
    spell = action.get('type') == 'cast_spell' and p and any(t in p.types for t in ('instant', 'sorcery'))
    if spell and re.fullmatch(r'\s*you win the game[.!]?\s*', text):
        return W.lethal, 'startable'
    if action.get('type') == 'cast_spell' and 'alt-win' in ctx.roles(action):
        # A permanent's upkeep condition is setup, not an immediate win.
        goal = re.search(r'if you have (\d+) or more life', ctx.text(action))
        if goal and number(ctx.me.get('life'), 40) >= int(goal[1]):
            return W.combo_cap, 'reachable'
    # Nonconditional direct table damage can close a game. Triggered clauses
    # on a permanent are not counted as immediately dealt damage.
    if action.get('type') == 'cast_spell' and (ctx.plan(action) and any(t in ctx.plan(action).types for t in ('instant', 'sorcery'))):
        m = re.search(r'(?:deals? (\d+|x) damage to each opponent|each opponent loses (\d+|x) life)', text)
        if m and 'if ' not in text:
            amount = next(g for g in m.groups() if g)
            amount = number(action.get('x')) if amount == 'x' else number(amount)
            if ctx.opponents and all(amount >= number(p.get('life'), 40) for p in ctx.opponents):
                return W.lethal, 'startable'
    progress, status = combo_progress(ctx, action)
    return progress, status
