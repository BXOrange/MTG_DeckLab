from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _card() -> list[AbilitySpec]:
    "When Meathook Massacre II enters, each player sacrifices X creatures of their choice.\nWhenever a creature you control dies, you may pay 3 life. If you do, return that card under your control with a finality counter on it.\nWhenever a creature an opponent controls dies, they may pay 3 life. If they don't, return that card under your control with a finality counter on it."
    return [
        AbilitySpec(
            'triggered',
            [EffectSpec('measured_edict', {"amount": {'kind': 'x_paid'}, "selector": 'each_player'})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {'subject': 'self'}},
            raw_text='',
        ),
        AbilitySpec(
            'triggered',
            [EffectSpec('pay_cost_then', {"cost": {'pay_life': 3}, "payer": 'controller', "effects": [{'type': 'return_dying_subject_to_battlefield', 'params': {'under_your_control': True, 'extra_counters': {'finality': 1}}}]})],
            trigger={"event": EventType.DIES, "condition": {'subject': 'group', 'controller': 'you', 'type': 'creature'}},
            raw_text='',
        ),
        AbilitySpec(
            'triggered',
            [EffectSpec('pay_cost_then', {"cost": {'pay_life': 3}, "payer": 'event_controller', "else_effects": [{'type': 'return_dying_subject_to_battlefield', 'params': {'under_your_control': True, 'extra_counters': {'finality': 1}}}]})],
            trigger={"event": EventType.DIES, "condition": {'subject': 'group', 'controller': 'not_you', 'type': 'creature'}},
            raw_text='',
        ),
    ]


register('Meathook Massacre II', _card)
