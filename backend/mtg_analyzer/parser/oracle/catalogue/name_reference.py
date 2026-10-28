"""Same-name operands composed with the existing operation grammar."""
from __future__ import annotations

import re
from .clause_hooks import parse_effect_body
from .clause_reading import ClauseReading
from ..spec import EffectSpec
from .name_atoms import name_reference
from .object_phrase import parse_operand
from .subgrammars import resolve_target_kind

_SEARCH = re.compile(
    r"(?P<before>.+?)\. search its (?P<who>controller|owner)'s graveyard, hand, and library "
    r"for (?P<quantity>all|any number of) cards with the same name as that "
    r"(?:spell|card|creature|artifact|enchantment|land|permanent) and exile them\. then that player shuffles\.?"
)
_CHOOSE_GRAVEYARD = re.compile(r"choose target card in a graveyard other than a basic land card")


def same_name_specs(body: str, reading: ClauseReading):
    search = _reference_search(body, reading)
    if search is not None:
        return search
    match = _SEARCH.fullmatch(body)
    if match is None:
        return None
    if _CHOOSE_GRAVEYARD.fullmatch(match['before']):
        before = [EffectSpec('choose_targets', {
            'kinds': ['any_graveyard_card'], 'creature_filter': {'not_basic_land': True},
        })]
    else:
        before = parse_effect_body(match['before'], reading=reading)
        # A single object provides both the name and the pre-move controller.
        if not before or len(before) != 1 or before[0].type not in {'counter', 'exile', 'destroy'}:
            return None
        if before[0].params.get('count', 1) != 1 or before[0].params.get('count_max') is not None:
            return None
        if (before[0].type != 'counter' and not before[0].params.get('target_kind')) or before[0].params.get('selector'):
            return None
    return [EffectSpec('same_name_search', {
        'effects': [effect.to_dict() for effect in before],
        'player_role': match['who'], 'any_number': match['quantity'] == 'any number of',
    })]


_NAME_SEARCH = re.compile(
    r"(?P<before>(?:you may )?search your library(?: and/or graveyard)? for .+?) "
    r"with the same name as (?P<reference>.+?)(?P<after>, (?:reveal|put).+)"
)


def _reference_search(body: str, reading: ClauseReading):
    match = _NAME_SEARCH.fullmatch(body.rstrip('.'))
    if match is None:
        return None
    ref = name_reference(match['reference'])
    announce = []
    if ref is None:
        operand = parse_operand(match['reference'], reading)
        if operand is None or operand.count != 1:
            return None
        if operand.kind == 'reference':
            ref = {'kind': operand.referent}
        elif operand.kind == 'target':
            kind = resolve_target_kind('target ' + operand.noun + {'you': ' you control', 'not_you': " you don't control"}.get(operand.controller, ''))
            if kind is None:
                return None
            announce = [EffectSpec('choose_targets', {'kinds': [kind],
                'creature_filter': operand.filter or {}})]
            ref = {'kind': 'target'}
        else:
            return None
    specs = parse_effect_body(match['before'] + match['after'], reading=reading)
    if not specs:
        return None
    def bind(node):
        if node['type'] == 'search':
            node['params']['criteria']['name_reference'] = ref
            return True
        children = node.get('params', {}).get('effects', [])
        return len(children) == 1 and bind(children[0])
    nodes = [spec.to_dict() for spec in specs]
    if len(nodes) != 1 or not bind(nodes[0]):
        return None
    return announce + [EffectSpec(node['type'], node['params']) for node in nodes]
