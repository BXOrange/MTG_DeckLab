from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _dina_soul_steeper() -> list[AbilitySpec]:
    """Whenever you gain life, each opponent loses 1 life.
    {1}, Sacrifice another creature: Dina gets +X/+0 until end of turn, where
    X is the sacrificed creature's power."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("lose_life", {"amount": 1, "selector": "each_opponent"})],
            trigger={"event": EventType.LIFE_GAINED, "condition": {"subject": "you"}},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("pump", {
                "power": 0, "toughness": 0,
                "amount_from_count_selector": "sacrificed_cost_power",
                "amount_from_count_selector_axis": "power",
            })],
            cost={"mana": "{1}", "text": "{1}, Sacrifice another creature"},
        ),
    ]


register("Dina, Soul Steeper", _dina_soul_steeper)
