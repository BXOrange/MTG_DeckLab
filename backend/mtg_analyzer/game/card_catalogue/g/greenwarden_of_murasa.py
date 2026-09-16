from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _greenwarden_of_murasa() -> list[AbilitySpec]:
    """Both recursion triggers of Greenwarden of Murasa."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("return_from_graveyard", {
                "target_kind": "graveyard_card", "destination": "hand",
            })],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {"subject": "self"},
            },
            optional=True,
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("may_exile_source_then", {"then_trigger": [
                {"type": "return_from_graveyard", "params": {
                    "target_kind": "graveyard_card", "destination": "hand",
                }},
            ]})],
            trigger={"event": EventType.DIES},
        ),
    ]


register("Greenwarden of Murasa", _greenwarden_of_murasa)
