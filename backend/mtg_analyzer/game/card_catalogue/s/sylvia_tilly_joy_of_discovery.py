
from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _sylvia_tilly_joy_of_discovery() -> list[AbilitySpec]:
    'When Sylvia Tilly enters, surveil 2. (Look at the top two cards of your library, then put any number of them into your graveyard and the rest on top of your library in any order.)\nAt the beginning of combat on your turn, you may pay {1} and exile a card from your graveyard. When you do, put a +1/+1 counter on target creature.'
    return [
        AbilitySpec(
            'triggered',
            [EffectSpec('surveil', {"count": 2})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {'subject': 'self'}},
            raw_text='when ~ enters, surveil 2.',
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("pay_cost_then", {
                "cost": "pay {1}, exile a card from your graveyard",
                "prompt": "{1} zahlen und eine Karte aus deinem Friedhof exilieren?",
                "then_trigger": [{"type": "add_counters", "params": {
                    "amount": 1, "kind": "+1/+1", "target_kind": "creature",
                }}],
            })],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "begin_combat"}, "phase_relation": "you"},
            raw_text="at the beginning of combat on your turn, you may pay {1} and exile a card from your graveyard. when you do, put a +1/+1 counter on target creature.",
        ),
    ]


register('Sylvia Tilly, Joy of Discovery', _sylvia_tilly_joy_of_discovery)
