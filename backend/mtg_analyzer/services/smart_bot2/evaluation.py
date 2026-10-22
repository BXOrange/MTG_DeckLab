"""Net action utility with bounded synergy and explicit opportunity costs."""
from __future__ import annotations
import re
from .context import W, LOW_HAND, DEVELOPMENT_SOURCES, LIFE_RESERVE, POISON_LETHAL, number
from .choices import sacrifice_value, target_value
from .profile import roles_for
from .recipes import recipe_vote


def reserve(ctx, actions):
    """Best concrete response/continuation, not an everlasting control label."""
    candidates = []
    for a in actions:
        text = ctx.effect_text(a)
        if 'counter target' in text and 'spell' in text and ctx.styles.get('reactivity', 0):
            candidates.append((min(W.reserve, W.reserve * ctx.styles.get('reactivity', 0)), ctx.cost(a), 'response'))
    # An accessible offered activation with a hit/attack prerequisite is a
    # real continuation. Public Oracle text supplies a bounded reserve for a
    # postcombat payment even when that continuation isn't offered yet.
    for o in ctx.ours:
        text = ctx.text(o)
        if 'combat damage' in text or 'attacks' in text:
            m = re.search(r'you may pay ((?:\{[^}]+\})+)', text)
            if m:
                from mtg_analyzer.services.bot_strategy import cost_requirements
                p, g = cost_requirements(m[1])
                candidates.append((W.reserve, sum(p.values()) + g, 'combat-continuation'))
    return max(candidates, default=(0.0, 0, 'none'))


def score(ctx, action, actions=()):
    text = ctx.effect_text(action)
    roles = roles_for(text)
    source_roles = ctx.roles(action)
    plan = ctx.plan(action)
    obj = ctx.obj(action)
    kind = action['type']
    cost = ctx.cost(action)
    terms = {'fallback': W.unknown, 'cost': -cost * W.cost}
    if kind == 'play_land':
        terms = {'land': W.land if ctx.sources < DEVELOPMENT_SOURCES else W.card,
                 'untapped': W.mana if action.get('enters_tapped') is False else 0}
        # Develop an affordable landfall engine before the drop if it enables
        # that very drop; choose again after the engine actually resolves.
        if any('landfall' in ctx.roles(o) for o in ctx.hand) and any(
            a['type'] == 'cast_spell' and 'landfall' in ctx.roles(a) for a in actions):
            terms['sequencing'] = -W.land
        return sum(terms.values()), terms, 'none'
    creature = obj.get('is_creature') or (plan and 'creature' in plan.types)
    permanent_cast = kind == 'cast_spell' and bool(plan and any(t in plan.types for t in ('creature', 'artifact', 'enchantment', 'planeswalker')))
    if kind == 'cast_spell':
        terms['development'] = W.card
        if plan and any(t in plan.types for t in ('instant', 'sorcery')):
            terms['card_spent'] = -W.card
        if creature:
            terms['body'] = W.body * (max(0, number(obj.get('power'))) + max(0, number(obj.get('toughness'))))
            terms['initiative'] = ctx.styles.get('initiative', 0) * W.synergy
        # An engine is useful only with matching accessible work, not solely
        # because it happens to be the commander.
        if source_roles & {'death-payoff', 'spellslinger', 'landfall', 'combat-hit', 'attack'}:
            terms['engine'] = W.engine * (1 + ctx.styles.get('engine', 0))
    else:
        terms['activation'] = -W.activation
    if 'ramp' in roles:
        terms['resource'] = W.mana * max(0, DEVELOPMENT_SOURCES - ctx.sources)
    if 'draw' in roles and (not permanent_cast or 'enters' in text):
        terms['cards'] = W.draw * (2 if len(ctx.hand) <= LOW_HAND else 1)
        m = re.search(r'draw (two|three|four|\d+)', text)
        if m:
            n = {'two': 2, 'three': 3, 'four': 4}.get(m[1], number(m[1], 1))
            terms['cards'] *= n
        for engine in ctx.ours:
            m = re.search(r'(?:if you have|with) (?:exactly )?(\d+) cards in (?:your )?hand', ctx.text(engine))
            if m and 'alt-win' in ctx.roles(engine) and len(ctx.hand) == int(m[1]):
                terms['preserve_hand_goal'] = -W.reserve - terms.get('cards', 0)
        if number(ctx.me.get('library_count'), 99) <= 1 and not any('library-win' in ctx.roles(o) for o in ctx.ours):
            terms['deckout'] = -W.lethal
    if 'tokens' in roles:
        terms['board'] = W.engine * (1 + ctx.styles.get('wide', 0))
    if 'lifegain' in roles:
        terms['life'] = W.mana if number(ctx.me.get('life'), 40) < LIFE_RESERVE else 0
    if roles & {'counter-synergy', 'landfall', 'reanimate', 'spellslinger', 'voltron', 'graveyard'}:
        # One saturated family vote, not one bonus for every matching regex.
        terms['synergy'] = W.synergy * max((ctx.styles.get(k, 0) for k in ('counters', 'lands', 'graveyard', 'spells', 'concentrated')), default=0)
    if 'proliferate' in roles:
        from .counters import proliferation_value
        terms['counter_delta'] = proliferation_value(ctx)
        terms['fallback'] = 0  # known action: no benefit merely for resolving
    life_cost = re.search(r'(\d+) life', str(action.get('cost_label', '')).casefold())
    if life_cost:
        amount = int(life_cost[1])
        terms['life_cost'] = -W.lethal if amount >= number(ctx.me.get('life'), 40) else -amount * W.cost
    if kind == 'activate_ability' and 'untap' in text:
        # Resource→untap→resource is a reusable operator. Count only explicit
        # printed mana and matching public additional-mana triggers.
        source_text = ctx.text(action)
        production = re.search(r'add ((?:\{[wubrgc]\})+)', source_text)
        if production:
            produced = production[1].count('{')
            extra = sum('whenever you tap a nonland permanent for mana' in ctx.text(o)
                        and 'add one mana' in ctx.text(o) for o in ctx.ours) if not obj.get('is_land') else 0
            net = produced + extra - cost
            terms['untap_resource'] = W.mana * net if net > 0 else 0
    if 'tutor' in roles:
        terms['selection'] = W.engine
    if 'counter' in roles and not permanent_cast:
        if not ctx.stack or ctx.owner({'stack_id': ctx.stack[-1].get('stack_id')}) == ctx.player_id:
            return -W.lethal, {'counter_without_opponent': -W.lethal}, 'none'
        threat = ctx.value(ctx.stack[-1].get('object') or {})
        terms['answer'] = threat - W.protection
        if ctx.roles(ctx.stack[-1].get('object') or {}) & {'alt-win', 'library-win'}:
            terms['urgent_answer'] = W.lethal
        for target in ctx.stack[-1].get('targets', []):
            if isinstance(target, dict) and ctx.owner(target) == ctx.player_id:
                terms['protect_target'] = max(terms.get('protect_target', 0), ctx.value(target))
    if 'wipe' in roles and (not permanent_cast or 'enters' in text):
        terms['symmetric'] = W.removal * (sum(ctx.value(o) for o in ctx.theirs if o.get('is_creature'))
                            - sum(ctx.value(o) for o in ctx.ours if o.get('is_creature')))
    targets = action.get('targets', [])
    if targets and 'counter' not in roles:
        polarity = 'harmful' if roles & {'removal', 'bounce'} else 'beneficial'
        terms['targets'] = sum(target_value(ctx, a, text, polarity) for a in targets) * W.removal
    if action.get('attach_kind'):
        terms['attachment'] = W.engine
        if targets and all(a.get('instance_id') == obj.get('attached_to') for a in targets):
            terms['no_progress'] = -W.lethal
    for key in ('sacrifice_choice', 'sacrifice_choices'):
        if action.get(key) is not None:
            ids = action[key] if isinstance(action[key], list) else [action[key]]
            terms['sacrifice'] = sum(sacrifice_value(ctx, {'instance_id': i}, text) for i in ids)
    if 'sacrifice' in str(action.get('cost_label', '')).casefold() and not any(k in terms for k in ('sacrifice',)):
        # Self-sacrifice is profitable for some effects, but it still loses
        # the source. Tutors and creature return engines can offset this.
        terms['source_lost'] = -ctx.value(obj)
    if action.get('discard_choices'):
        from .choices import discard_value
        terms['discard'] = sum(discard_value(ctx, {'instance_id': i}) for i in action['discard_choices'])
    rvalue, rcost, reason = reserve(ctx, actions)
    if ctx.mana and cost + rcost > ctx.mana and rcost and 'counter' not in roles:
        terms['reservation'] = -rvalue
    if 'x' in action:
        x = number(action['x'])
        terms['x_output'] = x * (W.draw if 'draw' in roles else W.body * 2)
    # Known once-per-turn cast engines: growing the resource before tapping
    # wins a tie if an affordable noncreature spell can improve this turn.
    if kind in ('tap_for_mana', 'activate_hand_mana'):
        terms['mana_unlock'] = W.mana
        if 'power' in text and 'once each turn' in ctx.text(action) and any(
            a['type'] == 'cast_spell' and not ctx.obj(a).get('is_creature') for a in actions):
            terms['grow_first'] = -W.reserve
    from .plans import trigger_value, continuation_value
    terms['triggers'] = trigger_value(ctx, action)
    terms['continuation'] = continuation_value(ctx, action, actions)
    vote, status = recipe_vote(ctx, action)
    terms['plan'] = vote
    # The decision trace distinguishes inferred plan progress from an engine
    # victory. Even +lethal is a policy proposal, never a stored win flag.
    return sum(terms.values()), terms, status
