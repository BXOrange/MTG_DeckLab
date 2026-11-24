from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _chief_montgomery_scott() -> list[AbilitySpec]:
    """Strange new worlds — {6}, {T}: You may put a creature or Spacecraft card from your hand onto the battlefield. It enters with X additional +1/+1 counters on it if it's a creature and X additional charge counters on it if it's a Spacecraft, where X is the number of differently named lands you control."""
    return [AbilitySpec('activated', [EffectSpec('bind', {
        'name': 'n', 'amount': {'kind': 'count_selector', 'selector': {
            'zone': 'battlefield', 'of': 'you', 'filter': {'card_type': 'land'}, 'distinct': 'name'}},
        'effects': [{'type': 'put_from_hand_onto_battlefield', 'params': {
            'criteria': {'type': ['Creature', 'Spacecraft']},
            'entry_counters_by_type': {'creature': {'+1/+1': '$n'}, 'spacecraft': {'charge': '$n'}},
        }}],
    })], cost={'mana': '{6}', 'taps_self': True})]


register('Chief Montgomery Scott', _chief_montgomery_scott)
