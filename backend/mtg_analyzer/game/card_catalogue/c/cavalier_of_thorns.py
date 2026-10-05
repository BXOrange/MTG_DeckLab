from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _cavalier_of_thorns() -> list[AbilitySpec]:
    return [
        AbilitySpec("keyword", [], keyword={"name": "reach"}),
        AbilitySpec(
            "triggered",
            [EffectSpec("inspect_top_choose", {
                "count": 5,
                "filter": {"is_land": True},
                "action": "library_to_battlefield",
                "rest_destination": "graveyard",
                "optional": False,
                "prompt": "Länderkarte auf das Spielfeld bringen (Rest in den Friedhof)",
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("may_exile_source_then", {"then_trigger": [
                {"type": "return_from_graveyard", "params": {
                    "target_kind": "graveyard_card", "destination": "library_top",
                }},
            ]})],
            trigger={"event": EventType.DIES},
        ),
    ]


register("Cavalier of Thorns", _cavalier_of_thorns)
