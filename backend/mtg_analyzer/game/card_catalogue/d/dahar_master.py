from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _dahar_master() -> list[AbilitySpec]:
    """When this creature enters, you may sacrifice another nonland permanent. When you do, this creature deals 2 damage to any target.

    RULE 603.12: the damage is a reflexive trigger that exists only if the
    sacrifice was paid (``pay_cost_then`` ``then_trigger``); RULE 701.21
    sacrifice of "another nonland permanent".
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("pay_cost_then", {
                "cost": "sacrifice another nonland permanent",
                "then_trigger": [{"type": "damage", "params": {"amount": 2, "target_kind": "any"}}],
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Dahar Master", _dahar_master)
