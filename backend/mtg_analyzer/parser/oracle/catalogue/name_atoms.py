"""Pure name operands shared by filters, searches and cast restrictions."""
from __future__ import annotations

import re

# A name may contain punctuation, including internal commas; the surrounding
# search grammar supplies the instruction boundary, not the first comma.
CARD_NAME = r"[a-z~](?:(?!, (?:then|draw|reveal|put|search|and|a card named)\b)[a-z0-9~'’,:&! -])*?"


def name_reference(text: str):
    """RULE 201.2a: an object or a set of objects whose names are compared."""
    if text == '~':
        return {'kind': 'source'}
    if text in {'the exiled card', 'a card exiled with ~', 'cards exiled with ~'}:
        return {'kind': 'linked_exile'}
    if text in {'enchanted creature', 'equipped creature', 'enchanted permanent'}:
        return {'kind': 'attached'}
    zone = re.fullmatch(r'a (?P<non>nontoken )?(?P<noun>card|permanent)(?: in (?P<who>your|their) (?P<zone>graveyard|hand))?', text)
    if zone:
        if zone['noun'] == 'card' and not zone['zone']:
            return None
        return {'kind': 'set', 'zone': zone['zone'] or 'battlefield',
                'of': ('you' if zone['who'] == 'your' else 'candidate_owner') if zone['zone'] else 'any',
                'nontoken': bool(zone['non'])}
    return None
