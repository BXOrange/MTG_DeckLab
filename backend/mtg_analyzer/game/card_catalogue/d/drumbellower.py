from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _drumbellower() -> list[AbilitySpec]:
    """Flying
    Untap all creatures you control during each other player's untap step."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("tap", {"selector": "creatures_you_control", "untap": True})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "untap"},
                     "phase_relation": "not_you"},
        ),
    ]


register("Drumbellower", _drumbellower)
