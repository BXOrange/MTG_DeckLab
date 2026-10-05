from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _dina_essence_brewer() -> list[AbilitySpec]:
    """Whenever you sacrifice a creature, draw a card. This ability triggers
    only once each turn.
    {2}, {T}, Sacrifice another creature: You gain X life and put X +1/+1
    counters on target creature you control, where X is the sacrificed
    creature's power."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={
                "event": EventType.SACRIFICE, "condition": {"subject": "you"},
                "sacrifice_type": "creature", "limit": True,
            },
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("gain_life", {"count_selector": "sacrificed_cost_power"}),
                EffectSpec("add_counters", {
                    "target_kind": "creature_you_control",
                    "amount_from_count_selector": "sacrificed_cost_power",
                }),
            ],
            cost={"mana": "{2}", "taps_self": True,
                  "text": "{2}, {T}, Sacrifice another creature"},
        ),
    ]


register("Dina, Essence Brewer", _dina_essence_brewer)
