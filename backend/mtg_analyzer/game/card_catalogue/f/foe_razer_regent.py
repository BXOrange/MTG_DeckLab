from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _foe_razer_regent() -> list[AbilitySpec]:
    """Flying
    When this creature enters, you may have it fight target creature you don't control.
    Whenever a creature you control fights, put two +1/+1 counters on it at the beginning of the next end step.

    — Flying is the printed keyword; the optional ETB fight is the parser's own claim, reproduced. The fight trigger
    is a RULE 603.1 group-subject trigger on `EventType.FIGHTS` (RULE 701.14: fired once per fighter after the
    damage). RULE 603.7: the counters are a delayed trigger created when it resolves; ``capture="trigger_subject"``
    fixes *which* creature fought now (RULE 603.7c), and the new `add_counters_to_captured` places the counters on
    it at the next end step -- of whichever player's turn it is (``scope="any"``) -- if it is still the same object.
    """
    return [
        AbilitySpec(
            'triggered',
            [EffectSpec('fight', {"other_kind": 'creature_you_dont_control'})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {'subject': 'self'}},
            optional=True,
            raw_text="when ~ enters, you may have it fight target creature you don't control.",
        ),
        AbilitySpec(
            'triggered',
            [EffectSpec('create_delayed_trigger', {
                "step": "end", "scope": "any", "capture": "trigger_subject", "trigger_event_key": "instance_id",
                "effects": [{"type": "add_counters_to_captured", "params": {"amount": 2, "kind": "+1/+1"}}],
            })],
            trigger={"event": EventType.FIGHTS, "condition": {"subject": "group", "controller": "you", "other": False}},
            raw_text="whenever a creature you control fights, put 2 +1/+1 counters on it at the beginning of the next end step.",
        ),
    ]


register('Foe-Razer Regent', _foe_razer_regent)
