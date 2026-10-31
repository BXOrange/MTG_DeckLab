"""Marginal counter utility from public state; no deck/card identity rules.

Proliferate selects recipients, not individual counter kinds (RULE 701.34a).
Unknown and redundant counters earn no speculative benefit.
"""
import re

from .context import W, POISON_LETHAL, number
from mtg_analyzer.parser.oracle.normalize import normalize as normalize_oracle

BENEFICIAL = frozenset({'+1/+1', 'loyalty', 'shield', 'energy', 'experience'})
HARMFUL = frozenset({'-1/-1', 'stun', 'poison', 'rad', 'age', 'doom', 'burden'})
# These counters normally store a spendable resource or progress. Require
# actual Oracle evidence before attributing value to an arbitrary named mark.
RESOURCES = frozenset({'charge', 'oil', 'quest', 'level', 'storage', 'ki', 'eon',
                       'training', 'growth', 'study', 'verse', 'page', 'brick',
                       'blood', 'coin', 'gem', 'luck', 'depletion', 'fade'})


def recipient_value(ctx, recipient, *, player=False):
    """Sum ALL marginal kinds on one recipient, including harmful collateral."""
    own = recipient.get('id' if player else 'controller_id') == ctx.player_id
    sign = 1 if own else -1
    text = '' if player else ctx.text(recipient)
    counters = dict(recipient.get('counters') or {})
    if player and number(recipient.get('poison')) > 0:
        counters['poison'] = recipient['poison']
    total = 0.
    # State-triggered counter wins are an immediate payoff, unlike a future
    # upkeep condition. Source-relative normalized prose avoids card-name rules.
    goals = {} if player else {
        kind: int(threshold) for threshold, kind in re.findall(
            r'when ~ has (\d+) or more ([a-z][a-z -]*) counters on it, you win the game',
            normalize_oracle(text, name=recipient.get('name')))
    }
    for raw, amount in counters.items():
        if number(amount) <= 0:
            continue
        kind = raw.casefold()
        value = 0.
        if kind in BENEFICIAL:
            value = W.synergy
        elif kind in HARMFUL:
            value = -W.synergy
        elif re.fullmatch(r'[+-]\d+/[+-]\d+', kind):
            # Less common P/T counters obey the same utility direction.
            power, toughness = (int(n) for n in kind.split('/'))
            value = W.body * (power + toughness)
        elif kind in RESOURCES and re.search(r'\b' + re.escape(kind) + r' counters?\b', text):
            value = W.synergy
        elif kind == 'time':
            # Vanishing removes one each upkeep: more time preserves a
            # permanent. Countdown-to-reward permanents have the opposite goal.
            if 'vanishing' in text:
                value = W.synergy
            elif re.search(r'(?:no|last) time counter', text):
                value = -W.synergy
        elif kind == 'ice' and re.search(r'(?:no|last) ice counter', text):
            value = -W.synergy
        elif kind == 'lore' and 'saga' in recipient.get('type_line', '').casefold():
            # Extra chapters may sacrifice a valuable Saga. Advance only when
            # another chapter remains afterwards; final-chapter value is unknown.
            chapter_groups = re.findall(r'(?m)^([ivx]+(?:\s*,\s*[ivx]+)*)\s*[—–-]', text)
            numerals = {'i': 1, 'v': 5, 'x': 10}
            def roman(token):
                values = [numerals[c] for c in token.strip()]
                return sum(-v if i + 1 < len(values) and v < values[i + 1] else v for i, v in enumerate(values))
            chapters = [roman(token) for group in chapter_groups for token in group.split(',')]
            if chapters and number(amount) + 1 < max(chapters):
                value = W.engine
        elif kind == 'defense' and recipient.get('protector_id'):
            # A Battle's protector wants its defense to survive.
            value = W.synergy if recipient['protector_id'] == ctx.player_id else -W.synergy
            total += value
            continue
        if kind in goals:
            threshold = goals[kind]
            value = W.lethal if number(amount) < threshold <= number(amount) + 1 else value
        # Duplicating flying/finality/etc. has no additional inherent benefit.
        if kind == 'poison' and number(amount) >= POISON_LETHAL - 1:
            value = -W.lethal
        total += sign * value
    if not player:
        toughness_delta = sum(int(kind.split('/')[1]) for kind, n in counters.items()
                              if number(n) > 0 and re.fullmatch(r'[+-]\d+/[+-]\d+', kind))
        if toughness_delta < 0 and number(recipient.get('toughness'), 1) + toughness_delta <= 0:
            total -= sign * ctx.value(recipient)
    return total


def proliferation_value(ctx):
    return sum(max(0., recipient_value(ctx, o)) for o in ctx.board) + sum(
        max(0., recipient_value(ctx, p, player=True)) for p in ctx.players if not p.get('has_lost'))


def proliferate_choice(ctx, options, decline):
    pending = ctx.view.get('pending_choice') or {}
    by_id = {o['id']: o for o in pending.get('options', [])}
    def value(action):
        option = by_id.get(str(action.get('option_id')), {})
        if option.get('player_id'):
            player = next((p for p in ctx.players if p['id'] == option['player_id']), {})
            return recipient_value(ctx, player, player=True)
        return recipient_value(ctx, ctx.obj(option))
    best = max(options, key=lambda a: (value(a), str(a.get('option_id'))))
    return best if value(best) > 0 else decline


def recommended_recipients(view, player_id):
    """The human picker and Smart bots share exactly the same marginal rule."""
    from .context import Context
    from .profile import build_profile
    ctx = Context(view, player_id, build_profile([], [], combos=[], named_signals=False))
    pending = view.get('pending_choice') or {}
    result = []
    for option in pending.get('options', []):
        if option.get('player_id'):
            player = next((p for p in ctx.players if p['id'] == option['player_id']), {})
            value = recipient_value(ctx, player, player=True)
        elif option.get('instance_id') is not None:
            value = recipient_value(ctx, ctx.obj(option))
        else:
            continue
        if value > 0:
            result.append(option['id'])
    return result
