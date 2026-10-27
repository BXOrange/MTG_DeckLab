"""Same-name operands composed with the existing operation grammar."""
from __future__ import annotations

import re
from .clause_hooks import parse_effect_body
from .clause_reading import ClauseReading
from ..spec import EffectSpec

_SEARCH = re.compile(
    r"(?P<before>.+?)\. search its (?P<who>controller|owner)'s graveyard, hand, and library "
    r"for (?P<quantity>all|any number of) cards with the same name as that "
    r"(?:spell|card|creature|artifact|enchantment|land|permanent) and exile them\. then that player shuffles\.?"
)
_CHOOSE_GRAVEYARD = re.compile(r"choose target card in a graveyard other than a basic land card")


def same_name_specs(body: str, reading: ClauseReading):
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
