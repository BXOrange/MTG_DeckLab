from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _abdel_adrian_gorions_ward() -> list[AbilitySpec]:
    """When Abdel Adrian enters, exile any number of other nonland
    permanents you control until Abdel Adrian leaves the battlefield.
    Create a 1/1 white Soldier creature token for each permanent exiled
    this way.
    Choose a Background (You can have a Background as a second commander.)

    RULE 610.3 returns the exiled incarnations immediately on departure.
    The chooser creates Soldiers from the number exiled this way.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("exile_any_number_you_control", {}),
            ],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Abdel Adrian, Gorion's Ward", _abdel_adrian_gorions_ward)
