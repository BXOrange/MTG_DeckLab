"""Two-action, visible-effect projections and trigger-aware continuation value.

Only well-understood mechanical deltas are projected. The actual next action
is always regenerated from the next server view, never from this projection.
"""
from __future__ import annotations
from collections import Counter
import re
from .context import W, number
from .profile import roles_for

# Discount uncertain future utility instead of pretending to search full turns.
CONTINUATION_DISCOUNT = .5
NUMBER_WORDS = {'one': 1, 'two': 2, 'three': 3, 'four': 4}


def expected_creature(ctx):
    """Own unordered deck minus visible copies, not hidden library contents."""
    outside = Counter(o.get('name', '').casefold() for o in ctx.objects
                      if o.get('owner_id', o.get('controller_id')) == ctx.player_id and not o.get('is_token'))
    weighted, total = 0.0, 0
    for name, plan in ctx.profile.cards.items():
        if 'creature' not in plan.types:
            continue
        remaining = max(0, ctx.profile.quantities.get(name, 0) - outside[name])
        evidence = getattr(ctx.profile, 'evidence', {}).get(name, {})
        value = W.card + plan.mana_value + W.body * (number(evidence.get('power')) + number(evidence.get('toughness')))
        weighted += remaining * value
        total += remaining
    return weighted / total if total else 0.0


def trigger_value(ctx, action):
    """Cast/land/second-spell trigger utility from public engines, not labels."""
    value = 0.0
    fact = ctx.view.get('turn_facts', {})
    cast_count = fact.get('spells_cast', {}).get(ctx.player_id, 0)
    plan = ctx.plan(action)
    if not plan:
        return value
    for engine in ctx.ours:
        text = ctx.text(engine)
        matching = action['type'] == 'cast_spell' and (
            'whenever you cast a spell' in text or
            ('noncreature spell' in text and 'creature' not in plan.types) or
            ('creature spell' in text and 'noncreature spell' not in text and 'creature' in plan.types) or
            ('artifact spell' in text and 'artifact' in plan.types) or
            ('instant or sorcery' in text and any(t in plan.types for t in ('instant', 'sorcery'))))
        if action['type'] == 'play_land' and 'landfall' in ctx.roles(engine):
            matching = True
        if 'second spell' in text:
            matching = action['type'] == 'cast_spell' and cast_count == 1
        if not matching:
            continue
        threshold = re.search(r'mana value (\d+) or greater', text)
        if threshold and plan.mana_value < int(threshold[1]):
            continue
        roles = ctx.roles(engine)
        gain = W.synergy
        if 'draw' in roles:
            gain += W.draw
        if 'tokens' in roles:
            gain += W.engine
        if 'drain' in roles:
            gain += W.combat_damage * len(ctx.opponents)
        if 'second spell' in text and 'copy' in text:
            gain += (W.card + ctx.cost(action)) * bool(action.get('targets'))
        if 'power' in text and 'greater' in text:
            for threshold in re.findall(r'power is (\d+) or greater', text):
                if number(ctx.obj(action).get('power')) >= int(threshold):
                    gain += W.synergy
        value += gain
    return value


def continuation_value(ctx, action, actions):
    """Conservative two-action lookahead for enabler→payoff and resources."""
    roles = ctx.roles(action)
    text = ctx.effect_text(action)
    cost = ctx.cost(action)
    value = 0.0
    if action['type'] == 'cast_spell' and 'landfall' in roles and any(a['type'] == 'play_land' for a in actions):
        value += W.land
    if action['type'] == 'cast_spell' and roles & {'spellslinger', 'death-payoff'}:
        compatible = [a for a in actions if a.get('instance_id') != action.get('instance_id')
                      and a['type'] == 'cast_spell' and ctx.cost(a) + cost <= ctx.mana]
        if compatible:
            value += W.engine * CONTINUATION_DISCOUNT
    if 'ramp' in roles:
        available = ctx.mana - cost
        # Explicit mana quantities only. A ritual must make usable progress;
        # don't repeatedly cast mana with no available follow-up plan.
        raw = re.search(r'add ((?:\{[wubrgc]\})+)', text)
        if raw:
            gain = raw[1].count('{')
            followups = [a for a in actions if a.get('instance_id') != action.get('instance_id')
                         and a['type'] == 'cast_spell' and available < ctx.cost(a) <= available + gain]
            if followups:
                value += W.reserve
    if ('reveal cards' in text or 'reveal a' in text) and ('exile' in text or 'destroy' in text):
        value += expected_creature(ctx)
    # Typal and broad anthems scale with the actual affected board. A
    # catalogue label or named lord alone contributes no points.
    anthem = re.search(r'(?:other )?(?:(?P<subtype>[a-z]+) )?creatures you control get \+(?P<p>\d+)/\+(?P<t>\d+)', text)
    if anthem:
        temporary = 'until end of turn' in text
        useful_window = ctx.active and ctx.step in ('main1','begin_combat','declare_blockers') or bool(ctx.stack)
        if not temporary or useful_window:
            subtype = anthem['subtype']
            affected = [o for o in ctx.ours if o.get('is_creature') and
                        (not subtype or subtype in o.get('type_line','').casefold().split())]
            value += len(affected) * (int(anthem['p']) + int(anthem['t'])) * W.body
    # An unconditional temporary pump is worth spending before combat only
    # with a real attacker. Generic synergy can't make an idle pump useful.
    if 'until end of turn' in text and ('gets +' in text or 'get +' in text):
        if ctx.active and ctx.step == 'main1' and any(o.get('is_creature') and not o.get('tapped')
                                                     and not o.get('summoning_sick') for o in ctx.ours):
            value += W.attack_trigger
        elif not ctx.stack:
            value -= W.reserve
    return value
