from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _selvala_heart_of_the_wilds() -> list[AbilitySpec]:
    """Whenever another creature enters, its controller may draw a card if
    its power is greater than each other creature's power.
    {G}, {T}: Add X mana in any combination of colors, where X is the
    greatest power among creatures you control.

    — MEC-43. The mana ability is a plain RULE 605 ability, parsed by
    `mana_abilities_for` rather than bound here. The trigger is the new
    `DrawIfTriggerObjectGreatestPowerEffect` — RULE 603.1's "its" resolves
    to the firing `ENTERS_BATTLEFIELD` event's own object, compared live
    against every other creature's derived power.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("draw_if_trigger_object_greatest_power", {})],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {"subject": "group", "type": "creature", "other": True},
            },
        ),
    ]


register("Selvala, Heart of the Wilds", _selvala_heart_of_the_wilds)
