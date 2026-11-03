from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _invasion_of_pyrulea() -> list[AbilitySpec]:
    "(As a Siege enters, choose an opponent to protect it. You and others can attack it. When it's defeated, exile it, then cast it transformed.)\nWhen this Siege enters, scry 3, then reveal the top card of your library. If it's a land or double-faced card, draw a card."
    return [
        AbilitySpec(
            'triggered',
            [EffectSpec('scry', {"count": 3}), EffectSpec('reveal_top', {}), EffectSpec('draw', {"count": 1}, condition={"kind": 'any', "conditions": [{'kind': 'is_card_type', 'card_type': 'land', 'of': 'revealed'}, {'kind': 'is_double_faced', 'of': 'revealed'}]})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {'subject': 'self'}},
            raw_text='',
        ),
    ]


register('Invasion of Pyrulea', _invasion_of_pyrulea)


def _gargantuan_slabhorn() -> list[AbilitySpec]:
    'Trample, ward {2}\nOther transformed permanents you control have trample and ward {2}.'
    return [
        AbilitySpec(
            'static',
            [EffectSpec('grant_keyword', {"affects": 'permanents_you_control', "exclude_self": True, "object_filter": {'transformed': True}, "keywords": ['trample'], "ward_cost": '{2}'})],
            raw_text='',
        ),
    ]


register('Gargantuan Slabhorn', _gargantuan_slabhorn)
