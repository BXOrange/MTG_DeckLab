from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _defiling_daemogoth() -> list[AbilitySpec]:
    """Menace
    Whenever a creature you control deals combat damage to a player, you gain
    1 life.
    At the beginning of your end step, each opponent loses X life, where X is
    the amount of life you gained this turn."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("gain_life", {"amount": 1})],
            trigger={
                "event": EventType.DAMAGE,
                "condition": {"subject": "group", "type": "creature", "other": False,
                              "controller": "you"},
                "filter": {"is_player": True, "combat": True},
            },
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("lose_life", {
                "selector": "each_opponent",
                "amount_from_count_selector": "life_gained_this_turn",
            })],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"},
                     "phase_relation": "you"},
        ),
    ]


register("Defiling Daemogoth", _defiling_daemogoth)
