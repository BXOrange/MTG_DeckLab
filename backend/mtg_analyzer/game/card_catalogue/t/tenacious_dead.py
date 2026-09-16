from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _tenacious_dead() -> list[AbilitySpec]:
    """When this creature dies, you may pay {1}{B}. If you do, return it
    to the battlefield tapped under its owner's control.

    — MEC-43 round 2. ``remember_trigger_subject`` (`PayCostThenEffect`)
    stamps the dying creature's own `instance_id` onto `GameObject.
    remembered_instance_id` before the interactive pay-or-decline choice
    opens (`context.trigger_event` is only live for the first, synchronous
    `apply()` call — the "if you do" branch runs later); the new
    `return_from_graveyard` `trigger_subject_key="remembered"` mode reads
    it back instead of taking a RULE 115 target, and the new ``tapped``
    param is the printed "return it to the battlefield **tapped**".
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("pay_cost_then", {
                "cost": "{1}{B}",
                "remember_trigger_subject": True,
                "effects": [{
                    "type": "return_from_graveyard",
                    "params": {"trigger_subject_key": "remembered", "tapped": True},
                }],
            })],
            trigger={"event": EventType.DIES, "condition": {"subject": "self"}},
        )
    ]


register("Tenacious Dead", _tenacious_dead)
