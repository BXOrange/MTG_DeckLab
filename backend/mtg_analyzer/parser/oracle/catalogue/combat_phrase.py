"""Combat instruction tails shared by standing and turn-limited effects.

Operands remain in the shared object grammar; this module only reads the
combat operation and its duration (RULE 508.1d, 509.1b-c, 510.1a).
"""
from __future__ import annotations

import re
from typing import Optional


def combat_tail(text: str, *, temporary: bool) -> Optional[tuple[str, dict]]:
    """Return the existing effect type and params, refusing unknown qualifiers."""
    if temporary:
        # RULE 611.2c: the duration belongs to this instruction, never the noun.
        prefix = text.startswith('until end of turn, ')
        text = text.removeprefix('until end of turn, ')
        text, count = re.subn(r' (?:this turn|until end of turn)(?= if able$|$)', '', text, count=1)
        if (not count and not prefix) or 'this turn' in text:
            return None
    elif 'this turn' in text:
        return None
    requirement = re.fullmatch(r'(attacks?|blocks?|attacks? or blocks?)(?: each combat)? if able', text)
    if requirement:
        action = requirement[1]
        if action.startswith('attack') and 'block' not in action:
            return 'grant_keyword', {'keywords': ['attacks_if_able']}
        if action.startswith('block'):
            return 'combat_restriction', {'kind': 'must_block_if_able'}
        # On your turn only attack requirements can apply, on another player's
        # turn only block requirements can apply (RULE 506.2).
        return 'both_requirements', {}
    extra = re.fullmatch(r'can block an additional (?:creature|(?P<n>\d+) creatures)(?: each combat)?', text)
    if extra:
        return 'combat_restriction', {'kind': 'extra_blocks', 'count': int(extra['n'] or 1)}
    if text == 'can block any number of creatures':
        return 'combat_restriction', {'kind': 'unlimited_blocks'}
    if re.fullmatch(r'assigns? combat damage equal to (?:its|their) toughness rather than (?:its|their) power', text):
        return 'combat_restriction', {'kind': 'damage_uses_toughness'}
    if text == 'can attack as though it didn\'t have defender' or text == 'can attack as though they didn\'t have defender':
        return 'combat_restriction', {'kind': 'attacks_as_though_no_defender'}
    if text in ("can't block", "can't attack", "can't attack or block"):
        flags = {'can\'t block': ['cant_block'], 'can\'t attack': ['cant_attack'],
                 'can\'t attack or block': ['cant_attack', 'cant_block']}[text]
        return 'grant_keyword', {'keywords': flags}
    return None
