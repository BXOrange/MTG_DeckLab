"""Factor exile target × return timing × entry instruction for bounded flickers."""
from __future__ import annotations
import re
from ..spec import EffectSpec
from .counters import COUNTER_KIND_PATTERN

_REFERENCE = r'(?:~|her|him|it|them|that card|those cards|that creature|that permanent|each of them|the exiled cards?)'
_SCHEDULE = re.compile(r'at the beginning of (?P<when>the next end step|your next end step|your next upkeep|the next combat)')
_RETURN = re.compile(rf'return {_REFERENCE} to the battlefield(?P<transformed> transformed)?(?P<tapped> tapped)? under (?P<who>your|(?:its|her|his) owner\'?s|their owners?\'s?) control(?P<tail>.*)')
_COUNTER = re.compile(rf'(?:with |and )(?:an? |(?P<count>\d+) )(?P<kind>{COUNTER_KIND_PATTERN}) counters?(?: on (?:it|them))?')
_RETURN_BODY_TYPES = frozenset({'draw', 'discard', 'gain_life', 'lose_life',
    'create_token', 'grant_until', 'seq', 'bind', 'if_else', 'optional'})


def _rider_specs(text):
    """Reuse known effect grammar, but never hide a newly announced target.

    These are continuations of one announced blink. Targeted instructions
    require their own announcement support and must remain unclaimed here.
    """
    from ..segmenter import parse_effect_body
    specs = parse_effect_body(text, previous_subject=True)
    if not specs:
        return None
    def safe(value):
        if isinstance(value, dict):
            if value.get('type') and 'params' in value and value['type'] not in _RETURN_BODY_TYPES:
                return False
            if value.get('target_kind') or value.get('target'):
                return False
            # A grant's static payload is already checked by the static
            # grammar; it is not another resolving instruction/target.
            return all(safe(v) for k, v in value.items() if k != 'static')
        if isinstance(value, list):
            return all(safe(v) for v in value)
        return True
    return [s.to_dict() for s in specs] if all(safe(s.to_dict()) for s in specs) else None


def flicker_sequence_specs(body):
    """Only claim a complete exile/return instruction with understood riders.

    The target grammar is the existing exile builder; a future combination
    of known target, timing and entry axes needs no card-specific handler.
    """
    if not body.startswith('exile ') or 'return ' not in body:
        return None
    split = re.fullmatch(r'exile (?P<subject>.+?)(?:\. |,? then )(?P<return>.+?)\.?', body)
    if split is None:
        return None
    from ..segmenter import parse_effect_body
    subject = '~' if split['subject'] == 'this saga' else split['subject']
    exiled = parse_effect_body('exile ' + subject)
    if exiled is None or len(exiled) != 1 or exiled[0].type != 'exile':
        return None
    original = dict(exiled[0].params)
    if not original.get('target_kind') and split['subject'] not in {'~', 'this saga'}:
        return None
    if any(k not in {
        'target_kind', 'creature_filter', 'optional', 'count', 'count_max', 'target_count', 'target_count_max'
    } for k in original):
        return None
    text = split['return'].strip().rstrip('.')
    schedules = list(_SCHEDULE.finditer(text))
    if len(schedules) > 1:
        return None
    params = dict(original)
    if split['subject'] in {'~', 'this saga'}:
        params.pop('target_kind', None)
        params['subject'] = 'source'
    text = re.sub(r'^if you do, ', '', text)
    if params.get('optional'):
        params['target_count_max'] = params.pop('count_max', params.pop('count', 1))
    elif 'count' in params:
        params['target_count'] = params.pop('count')
    if 'count_max' in params:
        params['target_count_max'] = params.pop('count_max')
    if schedules:
        found = schedules[0]
        params['return_step'], params['return_scope'] = {
            'the next end step': ('end', 'any'),
            'your next end step': ('end', 'controller'),
            'your next upkeep': ('upkeep', 'controller'),
            'the next combat': ('begin_combat', 'any'),
        }[found['when']]
        text = (text[:found.start()] + text[found.end():]).strip(' ,.')
        if text.startswith('return '):
            pass
        elif text.startswith(', '):
            text = text[2:]
    returned = _RETURN.fullmatch(text)
    if returned is None:
        return None
    if returned['who'] == 'your':
        params['under_your_control'] = True
    if returned['tapped']:
        params['tapped'] = True
    if returned['transformed']:
        params['transformed'] = True
    tail = returned['tail'].strip(' .')
    conditional = re.fullmatch(r'(?P<entry>.*?)\.?\s*if you do, (?P<body>.+)', tail)
    if conditional:
        riders = _rider_specs(conditional['body'])
        if riders is None:
            return None
        params['return_effects'] = riders
        params['return_if_successful'] = True
        tail = conditional['entry'].strip(' .')
    elif tail and not tail.startswith(('with ', 'and ', 'each of them enters', 'if it enters', 'if a land enters')):
        riders = _rider_specs(tail)
        if riders is not None:
            params['return_effects'] = riders
            tail = ''
    if tail:
        typed = re.fullmatch(r"each of them enters with an additional \+1/\+1 counter on it if it's a creature and an additional loyalty counter on it if it's a planeswalker", tail)
        creature_counter = re.fullmatch(r'if it enters as a creature, it enters with an additional \+1/\+1 counter on it', tail)
        land_tapped = re.fullmatch(r'if a land enters this way, it enters tapped', tail)
        if typed:
            params['typed_entry_counters'] = [
                {'kind': '+1/+1', 'count': 1, 'types': ['creature']},
                {'kind': 'loyalty', 'count': 1, 'types': ['planeswalker']},
            ]
        elif creature_counter:
            params['typed_entry_counters'] = [{'kind': '+1/+1', 'count': 1, 'types': ['creature']}]
        elif land_tapped:
            params['tapped_if_types'] = ['land']
        else:
            remaining, counters = tail, {}
            while remaining:
                counter = _COUNTER.match(remaining)
                if counter is None:
                    return None
                counters[counter['kind']] = counters.get(counter['kind'], 0) + int(counter['count'] or 1)
                remaining = remaining[counter.end():].strip()
            params['entry_counters'] = counters
    return [EffectSpec('blink', params)]
