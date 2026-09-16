from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _omnath_locus_of_the_roil() -> list[AbilitySpec]:
    """When this creature enters, it deals damage to any target equal to the
    number of Elementals you control.
    Landfall — Whenever a land enters under your control, put a +1/+1 counter
    on this creature. If you control eight or more lands, draw a card."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {
                "target_kind": "any",
                "amount_from_count_selector": "creatures_you_control_of_type_elemental",
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [
                EffectSpec("add_counters", {"amount": 1, "kind": "+1/+1"}),
                EffectSpec("draw", {"count": 1}, condition={
                    "count_selector_at_least": {"selector": "lands_you_control", "count": 8},
                }),
            ],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {"subject": "group", "type": "land", "controller": "you"},
            },
        ),
    ]


register("Omnath, Locus of the Roil", _omnath_locus_of_the_roil)
