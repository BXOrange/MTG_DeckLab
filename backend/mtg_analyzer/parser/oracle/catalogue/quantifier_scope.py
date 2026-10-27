"""Quantified sets, shared by object operands and per-member instructions.

The set is data for the existing selector resolver, never a new effect family.
Contextual controller scopes require an antecedent; their identity is read at
resolution (RULE 608.2h), while ordinary scopes retain the meaning of "you".
"""
from __future__ import annotations

import re
from typing import Optional

from .clause_reading import ClauseReading, PLAYER, TARGET
from .count_phrase import parse_count_phrase
from ..spec import EffectSpec

PLAYER_SETS = {
    'each player': 'each_player', 'all players': 'each_player',
    'each opponent': 'each_opponent', 'all opponents': 'each_opponent',
    'each other player': 'each_other_player', 'all other players': 'each_other_player',
}
_CONTROLLER = re.compile(
    r" (?P<who>that player|that (?:creature|permanent|planeswalker)'s controller|"
    r"that player or that planeswalker's controller) controls?(?= |$)"
)


def object_set(text: str, reading: ClauseReading) -> Optional[dict]:
    """A noun set, including its controller and all recognized qualifiers."""
    text = text.strip()
    text = re.sub(r"\beach opponent controls\b", "your opponents control", text)
    controller = _CONTROLLER.search(text)
    ref = None
    if controller:
        if controller['who'] == 'that player':
            ref = 'previous_player' if any(r.kind == PLAYER for r in reading.referents) else 'trigger_player'
        else:
            if not reading.previous_subject or any(r.kind == TARGET and r.group for r in reading.referents):
                return None
            ref = 'previous_subject'
        text = text[:controller.start()] + text[controller.end():]
    selector = parse_count_phrase(text)
    if (selector is None or selector.get('zone') != 'battlefield'
            or any(k in selector for k in ('terms', 'distinct', 'aggregate'))):
        return None
    if ref:
        if selector.get('of') != 'any':
            return None
        selector = {**selector, 'of': 'context', 'controller_ref': ref}
        if ref == 'trigger_player':
            selector['event_player_events'] = ['SPELL_CAST', 'DAMAGE', 'ATTACKS', 'BECOMES_TARGET',
                                               'CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER', 'STEP_BEGIN']
    return selector


def quantified_set(text: str, reading: ClauseReading) -> Optional[dict]:
    if text in PLAYER_SETS:
        scope = {'players': PLAYER_SETS[text]}
        if scope['players'] == 'each_other_player' and any(r.kind == PLAYER for r in reading.referents):
            scope['except_player_ref'] = 'previous_player'
        return scope
    match = re.fullmatch(r'(?:each|all) (?P<noun>.+)', text)
    if match is None:
        return None
    selector = object_set(match['noun'], reading)
    return {'selector': selector} if selector is not None else None


def per_member_amount_specs(text: str, parse) -> Optional[list]:
    """An amount depending on a player in the set is measured inside the loop.

    "You" in the rest of the effect keeps naming the ability's controller.
    Only the count's owner changes; setting the whole acting player would
    incorrectly change unrelated effects in that same instruction.
    """
    sets = list(re.finditer(r'\beach (?:other player|player|opponent)\b', text))
    count = re.search(r' equal to the number of (?P<objects>.+?) (?:they control|in their (?P<zone>hand|graveyard|library))$', text)
    if len(sets) != 1 or count is None:
        return None
    member = sets[0]
    if member.end() > count.start() or 'target' in text:
        return None
    suffix = ' you control' if count['zone'] is None else ' in your ' + count['zone']
    rewritten = (text[:member.start()] + 'target player' + text[member.end():count.start()]
                 + ' equal to the number of ' + count['objects'] + suffix)
    inner = parse(rewritten)
    if not inner or len(inner) != 1 or inner[0].type != 'bind':
        return None
    params = inner[0].params
    amount = params.get('amount') or {}
    effects = params.get('effects') or []
    if (amount.get('kind') != 'count_selector' or (amount.get('selector') or {}).get('of') != 'you'
            or len(effects) != 1 or effects[0].get('params', {}).get('target_kind') != 'player'):
        return None
    bound = EffectSpec('bind', {**params, 'amount': {**amount, 'of': 'target'}})
    return [EffectSpec('for_each', {'over': quantified_set(member.group(), ClauseReading()),
                                   'effects': [bound.to_dict()]})]
