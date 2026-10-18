"""Factor exile target × return timing × entry instruction for bounded flickers."""
from __future__ import annotations
import re
from ..spec import EffectSpec
from .counters import COUNTER_KIND_PATTERN

_REFERENCE = r'(?:~|her|him|it|them|that card|those cards|that creature|that permanent|each of them|the exiled cards?)'
_SCHEDULE = re.compile(r'at the beginning of (?P<when>the next end step|your next end step|your next upkeep|the next combat)')
_RETURN = re.compile(rf'return {_REFERENCE} to the battlefield(?P<transformed> transformed)?(?P<face_down> face down)?(?P<tapped> tapped)?(?: under (?P<who>your|(?:its|her|his) owner\'?s|their owners?\'s?) control)?(?P<tail>.*)')
_COUNTER = re.compile(rf'(?:with |and )(?:an? |(?P<count>\d+) )(?P<kind>{COUNTER_KIND_PATTERN}) counters?(?: on (?:it|them))?')
_RETURN_BODY_TYPES = frozenset({'draw', 'discard', 'gain_life', 'lose_life',
    'create_token', 'grant_until', 'seq', 'bind', 'if_else', 'optional'})


def source_return_specs(body):
    """A named source returning with entry data, without exiling it again."""
    if 'where x is ' in body:
        return None  # the shared measurement wrapper must capture X first
    matched = re.fullmatch(
        rf'return ~ to the battlefield(?P<tapped> tapped)?'
        rf"(?: under (?P<who>your|its owner'?s) control)?"
        rf'(?: with (?P<count>a|an|\d+|x) (?P<counter>{COUNTER_KIND_PATTERN}) counters? on it)?'
        r'(?P<tail>(?: and |\. ).+)?\.?', body)
    if matched is None:
        return None
    params = {'tapped': bool(matched['tapped'])}
    if matched['who'] in (None, 'your'):
        params['under_your_control'] = True
    if matched['counter']:
        count = matched['count']
        params['extra_counters'] = {'kind': matched['counter'],
            'count': 'x' if count == 'x' else 1 if count in ('a', 'an') else int(count)}
    specs = [EffectSpec('return_self_to_battlefield', params)]
    if matched['tail']:
        tail = re.sub(r'^(?: and |\. )', '', matched['tail']).rstrip('.')
        rider = _rider_specs(tail)
        if rider is None:
            return None
        specs.extend(EffectSpec(**spec) for spec in rider)
    return specs


def delayed_dying_return_specs(body):
    """Factor a death's captured subject, return timing and entry options.

    Only called for a DIES head: the pronoun names the event's card, even
    when the ability belongs to a different permanent or an emblem.
    """
    if not re.match(r'return (?:it|that card|that creature) to the battlefield', body):
        return None
    schedule = _SCHEDULE.search(body)
    if schedule is None or body[schedule.end():].strip(' .'):
        return None
    from ..segmenter import parse_effect_body
    returned = parse_effect_body(body[:schedule.start()].strip().rstrip('.'), self_subject=True)
    if not returned or len(returned) != 1 or returned[0].type != 'return_self_to_battlefield':
        return None
    params = dict(returned[0].params)
    if any(key not in {'tapped', 'under_your_control', 'extra_counters', 'target_kind'} for key in params):
        return None
    params.pop('target_kind', None)
    when = schedule['when']
    params.update(step='upkeep' if 'upkeep' in when else 'begin_combat' if 'combat' in when else 'end',
                  scope='controller' if when.startswith('your') else 'any')
    return [EffectSpec('delay_return_dying_subject', params)]


def _rider_specs(text, *, live_returned=True):
    """Reuse known effect grammar, but never hide a newly announced target.

    These are continuations of one announced blink. Targeted instructions
    require their own announcement support and must remain unclaimed here.
    """
    from ..segmenter import parse_effect_body
    specs = parse_effect_body(text, previous_subject=True)
    if not specs and live_returned:
        # Here the previous subject is a freshly returned permanent,
        # after all entry choices. Ordinary destruction/exile tails must
        # keep rejecting live characteristic reads without LKI.
        from .referent_condition import TYPE_CONDITION_PATTERN, parse_referent_condition
        matched = re.fullmatch(rf'if (?P<condition>{TYPE_CONDITION_PATTERN}), (?P<body>.+)', text)
        if matched is not None and not matched['neg'].startswith('was'):
            condition = parse_referent_condition(matched['condition'])
            inner = parse_effect_body(matched['body'], previous_subject=True)
            def returned_subject(value):
                if value['kind'] in {'all', 'any'}:
                    return {**value, 'conditions': [returned_subject(v) for v in value['conditions']]}
                if value['kind'] == 'not':
                    return {**value, 'condition': returned_subject(value['condition'])}
                return {**value, 'of': 'previous_target'}
            if condition and inner:
                specs = [EffectSpec('if_else', {'condition': returned_subject(condition),
                    'then': [spec.to_dict() for spec in inner], 'else': []})]
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


def flicker_sequence_specs(body, *, self_subject=False):
    """Only claim a complete exile/return instruction with understood riders.

    The target grammar is the existing exile builder; a future combination
    of known target, timing and entry axes needs no card-specific handler.
    """
    if not body.startswith('exile ') or 'return ' not in body:
        return None
    conditional = _pre_exile_control_branch(body)
    if conditional is not None:
        return conditional
    split = re.fullmatch(r'exile (?P<subject>.+?)(?:\. |,? then )(?P<return>.+?)\.?', body)
    if split is None:
        return None
    from ..segmenter import parse_effect_body
    subject = split['subject']
    if subject == 'this saga' or (self_subject and subject in {'it', 'him', 'her'}):
        subject = '~'
    event_group = re.fullmatch(r'each creature that (?P<action>crewed|saddled) (?:it|~) this turn', subject)
    if event_group:
        original = {'subject': 'event_visits',
            'trigger_event_key': {'crewed': 'crewed_by_visits', 'saddled': 'saddled_by_visits'}[event_group['action']],
            'creature_filter': {'card_type': 'creature'}}
    else:
        exiled = parse_effect_body('exile ' + subject)
        if exiled is None or len(exiled) != 1 or exiled[0].type != 'exile':
            return None
        original = dict(exiled[0].params)
        if not original.get('target_kind') and subject != '~':
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
    if subject == '~':
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
    # RULE 110.2a: an unspecified recipient is the instructed player.
    if returned['who'] in (None, 'your'):
        params['under_your_control'] = True
    if returned['tapped']:
        params['tapped'] = True
    if returned['transformed']:
        params['transformed'] = True
    if returned['face_down']:
        if returned['transformed']:
            return None
        # Ordinary 2/2 face-down characteristics; this does not grant the
        # manifest/cloak permission to pay a creature card's mana cost.
        params['face_down_kind'] = 'morph'
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


def _pre_exile_control_branch(body):
    """Freeze the branch and acting player before exile resets control."""
    matched = re.fullmatch(r'exile (?P<subject>.+?)\. if you controlled it, '
        r'(?P<return>return .+?)\. otherwise, its controller (?P<verb>creates|draws|gains|loses|discards) (?P<body>.+?)\.?', body)
    if matched is None:
        return None
    from ..segmenter import parse_effect_body
    exiled = parse_effect_body('exile ' + matched['subject'])
    if not exiled or len(exiled) != 1 or exiled[0].type != 'exile' or not exiled[0].params.get('target_kind'):
        return None
    returned = matched['return']
    if re.fullmatch(rf'return {_REFERENCE} to the battlefield(?: tapped)?', returned):
        returned += " under its owner's control"
    blink = flicker_sequence_specs('exile ' + matched['subject'] + '. ' + returned)
    verb = {'creates': 'create', 'draws': 'draw', 'gains': 'gain', 'loses': 'lose', 'discards': 'discard'}[matched['verb']]
    otherwise = _rider_specs(verb + ' ' + matched['body'], live_returned=False)
    if not blink or not otherwise:
        return None
    return [EffectSpec('if_else', {
        'condition': {'kind': 'is_you', 'of': 'target'},
        'then': [spec.to_dict() for spec in blink],
        'else': [{'type': 'trigger_subject_referent', 'params': {
            'referent': 'target', 'acting': 'controller',
            'effects': [spec.to_dict() for spec in exiled] + otherwise}}],
    })]


def linked_pool_return_specs(body):
    """A shared source-linked pool, filtered by printed card types."""
    matched = re.fullmatch(
        r'return (?:all|each) (?:(?P<types>(?:(?:artifact|battle|creature|enchantment|land|planeswalker) )+))?'
        r'cards? exiled with (?:~|it) to the battlefield(?P<tapped> tapped)? '
        r"under (?P<who>your|its owner'?s|their owners?'?s?) control\.?", body)
    if matched is None:
        return None
    params = {}
    if matched['types']:
        params['card_types'] = matched['types'].split()
    if matched['tapped']:
        params['tapped'] = True
    if matched['who'] == 'your':
        params['under_your_control'] = True
    return [EffectSpec('return_all_exiled_with', params)]
