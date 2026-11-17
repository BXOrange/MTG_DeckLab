from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _card() -> list[AbilitySpec]:
    "At the beginning of your upkeep, you may sacrifice a Forest. If you sacrifice a snow Forest this way, this creature gains trample until end of turn. If you don't sacrifice a Forest, sacrifice this creature and it deals 7 damage to you.\n{T}: This creature deals damage equal to its power to another target creature. That creature deals damage equal to its power to this creature."
    return [
        AbilitySpec(
            'activated',
            [EffectSpec('damage_equal_to_power', {"target_kind": 'creature', "excludes_source": True}), EffectSpec('damage_equal_to_power', {"target_kind": None, "dealer_kind": 'previous_target', "recipient": 'source'})],
            cost={"text": '{t}'},
            raw_text='{t}: ~ deals damage equal to its power to another target creature. that creature deals damage equal to its power to ~.',
        ),
        AbilitySpec(
            'triggered',
            [EffectSpec('pay_cost_then', {"cost": {'sacrifice': 'forest'}, "effects": [{'type': 'snow_sacrifice_reward', 'params': {}}], "else_effects": [{'type': 'seq', 'params': {'effects': [{'type': 'sacrifice_self', 'params': {}}, {'type': 'damage', 'params': {'amount': 7, 'selector': 'controller'}}]}}]})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {'step': 'upkeep'}, "phase_relation": 'you'},
            raw_text='',
        ),
    ]


register('Gargantuan Gorilla', _card)
