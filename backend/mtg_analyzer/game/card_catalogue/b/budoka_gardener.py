from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _budoka_gardener() -> list[AbilitySpec]:
    '{T}: You may put a land card from your hand onto the battlefield. If you control ten or more lands, flip this creature.'
    return [
        AbilitySpec(
            'activated',
            [EffectSpec('put_from_hand_onto_battlefield', {"criteria": {'type': 'land'}, "count": 1}), EffectSpec('flip', {"source_only": True}, condition={"kind": 'control_count', "selector": {'zone': 'battlefield', 'of': 'you', 'filter': {'card_type': 'land'}}, "min": 10})],
            cost={"text": '{t}'},
            optional=True,
            raw_text='{t}: you may put a land card from your hand onto the battlefield. if you control 10 or more lands, flip ~.',
        ),
    ]


register('Budoka Gardener', _budoka_gardener)


def _dokai_weaver_of_life() -> list[AbilitySpec]:
    '{4}{G}{G}, {T}: Create an X/X green Elemental creature token, where X is the number of lands you control.'
    return [
        AbilitySpec(
            'activated',
            [EffectSpec('create_token', {"count": 1, "token_name": 'Elemental', "colors": ['G'], "subtypes": ['Elemental'], "pt_amount": {'kind': 'count_selector', 'selector': 'lands_you_control'}})],
            cost={"text": '{4}{G}{G}, {T}'},
            raw_text='',
        ),
    ]


register('Dokai, Weaver of Life', _dokai_weaver_of_life)
