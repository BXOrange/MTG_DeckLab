
from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _soulherder() -> list[AbilitySpec]:
    "Whenever a creature is exiled from the battlefield, put a +1/+1 counter on this creature.\nAt the beginning of your end step, you may exile another target creature you control, then return that card to the battlefield under its owner's control."
    return [
        AbilitySpec(
            'triggered',
            [EffectSpec('blink', {"target_kind": 'other_creature_you_control'})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {'step': 'end'}, "phase_relation": 'you'},
            optional=True,
            raw_text="at the beginning of your end step, you may exile another target creature you control, then return that card to the battlefield under its owner's control.",
        ),
        AbilitySpec("triggered", [EffectSpec("add_counters", {"count": 1, "kind": "+1/+1"})],
                    trigger={"event": EventType.EXILE,
                             "condition": {"subject": "group", "type": "creature"},
                             "filter": {"from_zone": "battlefield"}}),
    ]


register('Soulherder', _soulherder)
