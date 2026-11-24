from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _card() -> list[AbilitySpec]:
    "Menace, trample\nAt the beginning of your upkeep, you may sacrifice an artifact, enchantment, or token. If you don't, tap this creature."
    return [
        AbilitySpec(
            'keyword',
            [],
            keyword={"name": 'trample'},
            raw_text='Menace, trample',
        ),
        AbilitySpec(
            'keyword',
            [],
            keyword={"name": 'menace'},
            raw_text='Menace, trample',
        ),
        AbilitySpec(
            'triggered',
            [EffectSpec('pay_cost_then', {"cost": {'sacrifice_count': [1, 'permanent'], 'sacrifice_filter': {'any_of': [{'card_type': 'artifact'}, {'card_type': 'enchantment'}, {'token': True}]}}, "else_effects": [{'type': 'tap', 'params': {'target_kind': 'source'}}]})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {'step': 'upkeep'}, "phase_relation": 'you'},
            raw_text='',
        ),
    ]


register('Devouring Sugarmaw', _card)
