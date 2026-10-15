"""Untargeted return of a dying enchanted host (RULE 400.7e)."""
from __future__ import annotations

import re
from ..spec import EffectSpec

_RETURN = re.compile(
    r"return (?:that card|that creature|that land|it) to "
    r"(?:(?P<hand>its owner's hand)|the battlefield(?P<tapped> tapped)? "
    r"under (?P<control>its owner's|your) control"
    r"(?: with (?P<count>a|an|\d+) (?P<kind>\+1/\+1|-1/-1) counters? on it)?)"
    r"(?P<tail>.*)"
)


def dying_host_return_specs(clause: str):
    """Caller must require an attached-permanent trigger subject.

    `this card` always denotes the Aura and is deliberately excluded from
    the host referent grammar. Every tail must be consumed in its entirety.
    """
    match = _RETURN.fullmatch(clause.rstrip('.'))
    if match is None:
        return None
    params = {'destination': 'hand' if match['hand'] else 'battlefield',
              'under_your_control': match['control'] == 'your',
              'tapped': bool(match['tapped'])}
    if match['count']:
        params['extra_counters'] = {'kind': match['kind'],
                                    'count': int(match['count']) if match['count'].isdigit() else 1}
    tail = match['tail']
    if tail == ', then return this card to the battlefield transformed under your control':
        params['return_source_transformed'] = True
    elif tail == ". if that card is returned to its owner's hand this way, you may pay {u}{u}{u}. if you do, return this card to its owner's hand":
        if not match['hand']:
            return None
        params['source_hand_mana_cost'] = '{u}{u}{u}'
    elif tail:
        return None
    return [EffectSpec('return_dying_subject_to_battlefield', params)]
