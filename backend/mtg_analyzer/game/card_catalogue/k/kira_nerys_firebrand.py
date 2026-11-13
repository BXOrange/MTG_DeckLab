from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _kira_nerys_firebrand() -> list[AbilitySpec]:
    """Trample
    If a creature you control would enter while you control an attacking creature, instead it enters tapped and
    attacking.
    Whenever another creature you control enters, it gets +1/+1 until end of turn.

    ENG-55: the replacement is the standing ``creatures_enter_attacking`` static (`continuous.
    enters_attacking_from_static`, consulted in `GameState.add_to_battlefield` before the entrant joins the
    battlefield, RULE 614.1); the engine then puts it into combat (RULE 508.4), and an effect that names its own
    defender keeps it (RULE 508.4e, `put_onto_battlefield_attacking`). The pump trigger is the parser's claim.
    """
    return [
        AbilitySpec("static", [EffectSpec("creatures_enter_attacking", {})],
            raw_text="if a creature you control would enter while you control an attacking creature, instead it enters tapped and attacking."),
        AbilitySpec(
            'triggered',
            [EffectSpec('pump', {"power": 1, "toughness": 1, "trigger_subject": True, "trigger_event_key": '__group_subject__'})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {'subject': 'group', 'controller': 'you', 'other': True, 'type': 'creature'}},
            raw_text='whenever another creature you control enters, it gets +1/+1 until end of turn.',
        ),
    ]


register('Kira Nerys, Firebrand', _kira_nerys_firebrand)
