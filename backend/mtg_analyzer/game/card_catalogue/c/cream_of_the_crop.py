from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _cream_of_the_crop() -> list[AbilitySpec]:
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("inspect_top_choose", {
                "count": "trigger_power",
                "action": "library_top",
                "rest_destination": "library_bottom_random",
                "optional": True,
                "decline_leaves_untouched": True,
                "prompt": "Eine Karte oben auf die Bibliothek legen (Rest nach unten)",
            })],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {"subject": "group", "type": "creature", "controller": "you"},
            },
        ),
    ]


register("Cream of the Crop", _cream_of_the_crop)
