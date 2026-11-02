from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _ezuri_claw_of_progress() -> list[AbilitySpec]:
    'Whenever a creature you control with power 2 or less enters, you get an experience counter.\nAt the beginning of combat on your turn, put X +1/+1 counters on another target creature you control, where X is the number of experience counters you have.'
    return [
        AbilitySpec(
            'triggered',
            [EffectSpec('add_player_counters', {"amount": 1, "kind": 'experience'})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {'subject': 'group', 'controller': 'you', 'other': False, 'type': 'creature', 'max_power': 2}},
            raw_text='whenever a creature you control with power 2 or less enters, you get an experience counter.',
        ),
        AbilitySpec(
            'triggered',
            [EffectSpec('add_counters', {"target_kind": 'other_creature_you_control', "amount": {'kind': 'count_selector', 'selector': 'experience_counters_you_have'}, "kind": '+1/+1'})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {'step': 'begin_combat'}, "phase_relation": 'you'},
            raw_text='',
        ),
    ]


register('Ezuri, Claw of Progress', _ezuri_claw_of_progress)
