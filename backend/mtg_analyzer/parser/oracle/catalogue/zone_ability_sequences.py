"""Source exile, quoted trigger, optional branches and measured return bodies."""
from __future__ import annotations

import re

from ..spec import EffectSpec, ParserProvenance


def exile_grant_specs(body):
    matched = re.fullmatch(r'exile ~\. if you do, it gains "(?P<inner>.+)"\.?', body)
    if matched is None:
        return None
    inner = re.fullmatch(r'(?P<head>.+?), if ~ is exiled, (?P<body>.+)', matched['inner'])
    if inner is None:
        return None
    from ..segmenter import parse_effect_body, segment_line

    # Parse the event head separately: its entering object does not change
    # the explicit source referent established by "if ~ is exiled".
    head = segment_line(inner['head'] + ', draw a card.', allow_spell_effect=False,
                        provenance=ParserProvenance(version='nested', source='rule:oracle'))
    if head.spec is None or head.spec.ability_kind != 'triggered' or head.extra_specs:
        return None
    text = inner['body'].rstrip('.')
    optional = re.fullmatch(r"you may (?P<yes>.+?)\. if you don't, (?P<no>.+)", text)
    if optional:
        yes = parse_effect_body(optional['yes'], self_subject=True)
        no = parse_effect_body(optional['no'], self_subject=True)
        if not yes or not no:
            return None
        effects = [EffectSpec('optional', {'effects': [s.to_dict() for s in yes],
                                          'else_effects': [s.to_dict() for s in no]})]
    else:
        effects = parse_effect_body(text, self_subject=True)
    if not effects:
        return None
    # Optional branches currently share no announcement for distinct
    # targets. Never introduce a target hidden behind the quoted choice.
    def safe(value):
        if isinstance(value, dict):
            return not value.get('target_kind') and all(safe(v) for v in value.values())
        if isinstance(value, list):
            return all(safe(v) for v in value)
        return True
    payload = [s.to_dict() for s in effects]
    if not safe(payload):
        return None
    return [EffectSpec('blink', {'subject': 'source', 'return_to_battlefield': False,
        'exile_effects': [EffectSpec('create_turn_trigger', {'trigger': head.spec.trigger,
                'effects': payload, 'grant_zone': 'exile'}).to_dict()]})]
