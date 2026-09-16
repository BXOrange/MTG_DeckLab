from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _eccentric_pestfinder() -> list[AbilitySpec]:
    """Trample
    At the beginning of each end step, if you gained life this turn, this
    creature becomes prepared."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("become_prepared", {})],
            trigger={
                "event": EventType.STEP_BEGIN, "filter": {"step": "end"},
                "active_if": {"kind": "gained_life_this_turn"},
            },
        ),
    ]


register("Eccentric Pestfinder", _eccentric_pestfinder)
register("Eccentric Pestfinder // Turn Stones", _eccentric_pestfinder)
