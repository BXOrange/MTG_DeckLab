"""Factor exile target × return timing × entry instruction for bounded flickers."""
from __future__ import annotations
import re
from ..spec import EffectSpec

_REFERENCE = r'(?:it|them|that card|those cards|that creature|that permanent|each of them|the exiled cards?)'
_SCHEDULE = re.compile(r'at the beginning of (?P<when>the next end step|your next upkeep|the next combat)')
_RETURN = re.compile(rf'return {_REFERENCE} to the battlefield(?P<tapped> tapped)? under (?P<who>your|its owner\'?s|their owners?\'s?) control(?P<tail>.*)')
_COUNTER = re.compile(r'(?:with |and )(?:an? |(?P<count>\d+) )(?P<kind>\+1/\+1|loyalty|flying|vigilance|lifelink) counters?(?: on (?:it|them))?')


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
    exiled = parse_effect_body('exile ' + split['subject'])
    if exiled is None or len(exiled) != 1 or exiled[0].type != 'exile':
        return None
    original = dict(exiled[0].params)
    if not original.get('target_kind') or any(k not in {
        'target_kind', 'creature_filter', 'optional', 'count', 'count_max', 'target_count', 'target_count_max'
    } for k in original):
        return None
    text = split['return'].strip().rstrip('.')
    schedules = list(_SCHEDULE.finditer(text))
    if len(schedules) > 1:
        return None
    params = dict(original)
    if 'count' in params:
        params['target_count'] = params.pop('count')
    if 'count_max' in params:
        params['target_count_max'] = params.pop('count_max')
    if schedules:
        found = schedules[0]
        params['return_step'], params['return_scope'] = {
            'the next end step': ('end', 'any'),
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
    tail = returned['tail'].strip(' .')
    if tail:
        typed = re.fullmatch(r"each of them enters with an additional \+1/\+1 counter on it if it's a creature and an additional loyalty counter on it if it's a planeswalker", tail)
        land_tapped = re.fullmatch(r'if a land enters this way, it enters tapped', tail)
        if typed:
            params['typed_entry_counters'] = [
                {'kind': '+1/+1', 'count': 1, 'types': ['creature']},
                {'kind': 'loyalty', 'count': 1, 'types': ['planeswalker']},
            ]
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
