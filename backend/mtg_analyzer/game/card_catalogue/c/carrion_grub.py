from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _carrion_grub() -> list[AbilitySpec]:
    """This creature gets +X/+0, where X is the greatest power among creature cards in your graveyard.
    When this creature enters, mill four cards. (Put the top four cards of your library into your graveyard.)

    — PLAY-ALL (Death Toll). The mill trigger is the parser's. The static is a layer-7d ``anthem`` on itself whose
    power count is a structured ``aggregate: max`` selector over the creature cards in your graveyard.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {
                "affects": "self", "power": 1, "toughness": 0,
                "power_count": {"zone": "graveyard", "of": "you", "filter": {"card_type": "creature"},
                                "aggregate": "max", "value": "power"},
            })],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("mill", {"count": 4})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Carrion Grub", _carrion_grub)
