from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _witch_of_the_moors() -> list[AbilitySpec]:
    """Deathtouch
    At the beginning of your end step, if you gained life this turn, each
    opponent sacrifices a creature of their choice and you return up to one
    target creature card from your graveyard to your hand."""
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("sacrifice", {"selector": "each_opponent", "what": "creature",
                                         "count": 1}),
                EffectSpec("return_from_graveyard", {
                    "target_kind": "graveyard_creature", "destination": "hand",
                    "optional": True,
                }),
            ],
            trigger={
                "event": EventType.STEP_BEGIN, "filter": {"step": "end"},
                "phase_relation": "you",
                "active_if": {"kind": "gained_life_this_turn"},
            },
        ),
    ]


register("Witch of the Moors", _witch_of_the_moors)
