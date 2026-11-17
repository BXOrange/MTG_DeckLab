from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _card() -> list[AbilitySpec]:
    "Flying, trample\nAt the beginning of your upkeep, sacrifice a creature other than this creature, then each opponent loses life equal to the sacrificed creature's power. If you can't sacrifice a creature, tap this creature and you lose 7 life."
    return [
        AbilitySpec(
            'keyword',
            [],
            keyword={"name": 'flying'},
            raw_text='Flying, trample',
        ),
        AbilitySpec(
            'keyword',
            [],
            keyword={"name": 'trample'},
            raw_text='Flying, trample',
        ),
        AbilitySpec(
            'triggered',
            [EffectSpec('sacrifice_with_riders', {"what": 'creature', "exclude_source": True, "success": [{'type': 'lose_life', 'params': {'selector': 'each_opponent', 'amount': {'kind': 'count_selector', 'selector': 'sacrificed_cost_power'}}}], "failure": [{'type': 'tap', 'params': {'target_kind': 'source'}}, {'type': 'lose_life', 'params': {'amount': 7}}]})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {'step': 'upkeep'}, "phase_relation": 'you'},
            raw_text='',
        ),
    ]


register('Xathrid Demon', _card)
