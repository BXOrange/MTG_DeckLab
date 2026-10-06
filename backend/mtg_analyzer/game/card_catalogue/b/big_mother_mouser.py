from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _big_mother_mouser() -> list[AbilitySpec]:
    """This creature enters with two +1/+1 counters on it.
    Whenever this creature attacks, double the number of +1/+1 counters on it.
    When this creature dies, create a number of 1/1 colorless Robot artifact creature tokens equal to the number of +1/+1 counters on this creature.

    — PLAY-ALL (Turtle Power!). The entry counters are oracle-derived and the attack trigger is the parser's claim (`double_counters_on_target`). The dies trigger `bind`s the
    last-known +1/+1 counters (the DIES event's snapshot, RULE 603.10a) into a `create_token` of Robot artifact creature tokens.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("double_counters_on_target", {"kind": "+1/+1", "mode": "previous_subject"})],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("bind", {
                "name": "n", "amount": {"kind": "counters", "counter": "+1/+1", "of": "self"},
                "effects": [{"type": "create_token", "params": {
                    "count": "$n", "power": 1, "toughness": 1, "subtypes": ["Robot"], "token_name": "Robot", "is_artifact": True,
                }}],
            })],
            trigger={"event": EventType.DIES, "condition": {"subject": "self"}},
        ),
    ]


register("Big Mother Mouser", _big_mother_mouser)
