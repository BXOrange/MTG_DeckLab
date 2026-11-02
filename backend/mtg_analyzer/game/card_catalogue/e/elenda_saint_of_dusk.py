from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _elenda_saint_of_dusk() -> list[AbilitySpec]:
    'Lifelink, hexproof from instants\nAs long as your life total is greater than your starting life total, Elenda gets +1/+1 and has menace. Elenda gets an additional +5/+5 as long as your life total is at least 10 greater than your starting life total.'
    return [
        AbilitySpec(
            'static',
            [EffectSpec('anthem', {"affects": 'self', "power": 1, "toughness": 1, "active_if": {'kind': 'life_over_starting_at_least', 'amount': 1}})],
            raw_text='',
        ),
        AbilitySpec(
            'static',
            [EffectSpec('grant_keyword', {"affects": 'self', "keywords": ['menace'], "active_if": {'kind': 'life_over_starting_at_least', 'amount': 1}})],
            raw_text='',
        ),
        AbilitySpec(
            'static',
            [EffectSpec('anthem', {"affects": 'self', "power": 5, "toughness": 5, "active_if": {'kind': 'life_over_starting_at_least', 'amount': 10}})],
            raw_text='',
        ),
    ]


register('Elenda, Saint of Dusk', _elenda_saint_of_dusk, suppress_keywords=('menace',))
