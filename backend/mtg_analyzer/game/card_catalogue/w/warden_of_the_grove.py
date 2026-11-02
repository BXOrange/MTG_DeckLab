
from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _warden_of_the_grove() -> list[AbilitySpec]:
    'At the beginning of your end step, put a +1/+1 counter on this creature.\nWhenever another nontoken creature you control enters, it endures X, where X is the number of counters on this creature. (Put X +1/+1 counters on the creature that entered or create an X/X white Spirit creature token.)'
    return [
        AbilitySpec(
            'triggered',
            [EffectSpec('add_counters', {"count": 1, "kind": '+1/+1'})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {'step': 'end'}, "phase_relation": 'you'},
            raw_text='at the beginning of your end step, put a +1/+1 counter on ~.',
        ),
        AbilitySpec("triggered", [EffectSpec("bind", {
            "name": "n", "amount": {"kind": "count_selector", "selector": "total_counters_on_source"},
            "effects": [{"type": "trigger_subject_referent", "params": {"effects": [
                {"type": "endure", "params": {"amount": "$n", "previous_subject": True}},
            ]}}],
        })], trigger={"event": EventType.ENTERS_BATTLEFIELD,
                      "condition": {"subject": "group", "type": "creature", "controller": "you", "other": True, "nontoken": True}}),
    ]


register('Warden of the Grove', _warden_of_the_grove)
