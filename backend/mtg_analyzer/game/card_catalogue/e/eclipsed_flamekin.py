from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _eclipsed_flamekin() -> list[AbilitySpec]:
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("inspect_top_choose", {
                "count": 4,
                "filter": {"subtypes": ["Elemental", "Island", "Mountain"]},
                "action": "reveal_library_to_hand",  # RULE 701.20a: only the revealed pick is shown, not the looked-at window
                "rest_destination": "library_bottom_random",
                "optional": True,
                "prompt": "Elemental-, Island- oder Mountain-Karte wählen",
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD},
        ),
    ]


register("Eclipsed Flamekin", _eclipsed_flamekin)
