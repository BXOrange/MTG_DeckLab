"""RULE 611.2: compose a duration with an independently parsed effect body.

Only effects with a represented continuous lifetime can be retimed. An
instantaneous action, an unknown condition or a second clock fails closed.
"""
from __future__ import annotations

import re
from ..spec import EffectSpec
from .clause_hooks import parse_effect_body

from .duration_phrase import FIXED_DURATIONS, FIXED_DURATION_PATTERN, CONDITIONAL_DURATION_PATTERN, condition_phrase
from .subgrammars import resolve_target_kind, target_kind_allowed, target_quality_filter
_DURATION = rf'(?:{FIXED_DURATION_PATTERN}|for as long as {CONDITIONAL_DURATION_PATTERN})'
_LEAD = re.compile(rf'(?P<duration>{_DURATION}), (?P<body>.+)', re.I | re.S)
_TAIL = re.compile(rf'(?P<body>.+?) (?P<duration>{_DURATION})', re.I | re.S)


def _retime(node, duration, condition):
    """Keep operand/choice wrappers, changing only their continuous leaves."""
    p = dict(node.params)
    if node.type == 'choose_targets':
        return node
    if node.type in ('for_each', 'seq', 'optional', 'bind', 'trigger_subject_referent'):
        key = 'effects' if 'effects' in p else 'then'
        if not p.get(key):
            return None
        children = [_retime(EffectSpec.from_dict(s), duration, condition) for s in p[key]]
        if any(s is None for s in children):
            return None
        return EffectSpec(node.type, {**p, key: [s.to_dict() for s in children]}, condition=node.condition)
    if node.type == 'pump':
        allowed = {'power', 'toughness', 'keywords', 'removed_keywords', 'target_kind', 'optional', 'count', 'count_max',
                   'creature_filter', 'previous_subject', 'referent', 'selector', 'self_subject'}
        if set(p) - allowed:
            return None
        statics = []
        if p.get('power') or p.get('toughness'):
            statics.append({'type': 'anthem', 'params': {'power': p.get('power', 0), 'toughness': p.get('toughness', 0)}})
        for key, kind in (('keywords', 'grant_keyword'), ('removed_keywords', 'remove_keyword')):
            if p.get(key):
                statics.append({'type': kind, 'params': {'keywords': p[key]}})
        if not statics:
            return None
        subject = {k: v for k, v in p.items() if k not in ('power', 'toughness', 'keywords', 'removed_keywords', 'selector')}
        if p.get('selector'):
            for static in statics:
                static['params']['affects'] = p['selector']
            subject.update(target_kind=None, lock_group=True)
        elif not p.get('target_kind') and not p.get('previous_subject'):
            subject.update({'target_kind': None, 'self_subject': True})
        p = {**subject, 'static': statics[0], 'extra_statics': statics[1:]}
    elif node.type == 'gain_control_until_eot':
        return EffectSpec(node.type, {**p, 'duration': duration, 'untap': False, 'haste': False,
                          **({'condition': condition} if condition else {})}, condition=node.condition)
    elif node.type in ('prevent_damage_shield', 'prevent_damage_from_target'):
        return EffectSpec(node.type, {**p, 'duration': duration,
                          **({'condition': condition} if condition else {})}, condition=node.condition)
    elif node.type != 'grant_until':
        return None
    if condition and condition.get('kind') == 'captured_player_is_monarch':
        return None  # needs a player antecedent; never guess the effect controller
    return EffectSpec('grant_until', {**p, 'duration': duration,
                      **({'condition': condition} if condition else {})}, condition=node.condition)


def duration_specs(text, reading):
    text = text.strip().rstrip('.').lower()
    match = _LEAD.fullmatch(text) or _TAIL.fullmatch(text)
    if match is None:
        return None
    word, body = match['duration'], match['body']
    if word == 'until end of turn':
        return None
    # A trailing clock modifies its own sentence, never earlier sentences
    # with independently permanent effects (Rootwise Survivor).
    unquoted = re.sub(r'"[^"\n]*"', '', body)
    if re.search(r'\.\s|\buntil\b|\bfor as long as\b', unquoted):
        return None
    condition = condition_phrase(word[len('for as long as '):]) if word.startswith('for as long as ') else None
    duration = 'for_as_long_as' if condition else FIXED_DURATIONS.get(word)
    if not duration:
        return None
    copy = re.fullmatch(r'(?P<may>you may have )?(?P<subject>~|it|that creature) becomes? a copy of (?P<template>.+)', body)
    if copy:
        template = copy['template']
        if copy['subject'] != '~' and not reading.previous_subject and not (
            condition and condition.get('kind') == 'source_attached_to_affected'):
            return None
        recipient = 'source' if copy['subject'] == '~' else ('attached' if condition and
            condition.get('kind') == 'source_attached_to_affected' else 'previous')
        params = {'duration': duration, 'recipient': recipient, 'optional': bool(copy['may'])}
        if condition:
            params['condition'] = condition
        if template == 'a creature card exiled with ~':
            params['template'] = 'linked'
        elif template in ('it', 'that creature') and reading.previous_subject:
            params['template'] = 'previous'
        else:
            kind = resolve_target_kind(template)
            if not template.startswith(('target ', 'another target ')) or not target_kind_allowed(kind, ('creature', 'artifact', 'permanent')):
                return None
            params.update(template='target', target_kind=kind, creature_filter=target_quality_filter(template))
        return [EffectSpec('copy_for_duration', params)]
    if condition and condition.get('of') == 'affected':
        who = re.search(r'\bthat ([a-z]+) (?:has|is|remains)', word)
        if who:
            subject = re.split(r"\b(?:gets?|gains?|loses?|has|becomes?|doesn'?t)\b", unquoted, maxsplit=1)[0].strip()
            if subject == '~' or (subject not in ('it', 'that ' + who[1]) and not re.search(r'\b' + who[1] + r's?\b', subject)):
                return None
    # A familiar clock supplies the existing verb/object grammar; it is
    # replaced only if every emitted leaf represents a continuous effect.
    specs = parse_effect_body(body + ' until end of turn', reading=reading)
    if not specs:
        specs = parse_effect_body(body + ' this turn', reading=reading)
    if not specs:
        specs = parse_effect_body(body, reading=reading)
    if not specs:
        return None
    out = [_retime(s, duration, condition) for s in specs]
    def has_lifetime(node):
        if node.type in ('grant_until', 'gain_control_until_eot', 'prevent_damage_shield', 'prevent_damage_from_target'):
            return True
        return any(has_lifetime(EffectSpec.from_dict(s)) for key in ('effects', 'then')
                   for s in node.params.get(key, []))
    return out if all(s is not None for s in out) and any(has_lifetime(s) for s in out) else None
