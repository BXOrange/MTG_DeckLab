from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _blowfly_infestation() -> list[AbilitySpec]:
    """Whenever a creature dies, if it had a -1/-1 counter on it, put a
    -1/-1 counter on target creature.

    The C3a "a creature dies" group subject (any controller) with a new
    `ConditionalEffect` ``dying_creature_had_counter`` gate on the DIES
    event's snapshotted ``counters`` (RULE 400.7), then an ordinary
    targeted ``add_counters``.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {
                "count": 1, "kind": "-1/-1", "target_kind": "creature",
            })],
            trigger={
                "event": "DIES",
                "condition": {"subject": "group", "type": "creature",
                              "controller": "any", "other": False},
                # RULE 603.4 intervening-if — only triggers (and only then
                # prompts for a target) if the dead creature had a -1/-1
                # counter on it.
                "dying_had_counter": "-1/-1",
            },
        ),
    ]


register("Blowfly Infestation", _blowfly_infestation)
