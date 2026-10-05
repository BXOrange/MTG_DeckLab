from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _shield_broker() -> list[AbilitySpec]:
    """When this creature enters, put a shield counter on target noncommander creature you don't control. You
    gain control of that creature for as long as it has a shield counter on it. (If it would be dealt damage or
    destroyed, remove a shield counter from it instead.)

    — Family Matters deck batch. The ETB is a shield `add_counters` on a noncommander creature you don't
    control (``is_commander: False``) followed by a `grant_until` layer-2 ``control_change`` on that same
    target (``previous_subject``) bounded by a RULE 611.2b ``for_as_long_as`` condition — it ends the moment
    the *affected* creature has no shield counter (the counter is spent absorbing damage or destruction).
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("add_counters", {
                    "kind": "shield", "count": 1, "target_kind": "creature_you_dont_control",
                    "creature_filter": {"is_commander": False},
                }),
                EffectSpec("grant_until", {
                    "static": {"type": "control_change", "params": {}},
                    "previous_subject": True, "target_kind": None,
                    "condition": {"kind": "source_counters", "counter": "shield", "min": 1, "of": "affected"},
                }),
            ],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Shield Broker", _shield_broker)
