from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _kinetic_ooze() -> list[AbilitySpec]:
    """This creature enters with X +1/+1 counters on it.
    When this creature enters, destroy up to one target artifact or
    enchantment with mana value X or less. If X is 5 or more, you draw a
    card. If X is 10 or more, double the number of +1/+1 counters on any
    number of other target creatures."""
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("destroy", {"target_kind": "artifact_or_enchantment",
                                       "max_mana_value": "x", "optional": True}),
                EffectSpec("draw", {"count": 1},
                           condition={"source_x_paid_at_least": 5}),
                EffectSpec("double_counters_on_target",
                           {"target_kind": "creature", "kind": "+1/+1"},
                           condition={"source_x_paid_at_least": 10}),
            ],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Kinetic Ooze", _kinetic_ooze)
