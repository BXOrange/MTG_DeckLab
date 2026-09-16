from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _emeria_the_sky_ruin() -> list[AbilitySpec]:
    """This land enters tapped.
    At the beginning of your upkeep, if you control seven or more Plains, you
    may return target creature card from your graveyard to the battlefield.
    {T}: Add {W}."""
    EMERIA_PLAINS_THRESHOLD = 7
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("return_from_graveyard", {
                "target_kind": "graveyard_creature", "destination": "battlefield",
                "optional": True,
            })],
            trigger={
                "event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"},
                "phase_relation": "you",
                "active_if": {
                    "kind": "control_count",
                    "selector": "lands_you_control_of_type_plains",
                    "min": EMERIA_PLAINS_THRESHOLD,
                },
            },
        ),
    ]


register("Emeria, the Sky Ruin", _emeria_the_sky_ruin)
