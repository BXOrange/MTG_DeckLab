from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ---------------------------------------------------------------------------
# MEC-74: Dance of the Elements — count-sensitive landfall / Elemental cards
# ---------------------------------------------------------------------------


def _avenger_of_zendikar() -> list[AbilitySpec]:
    """When this creature enters, create a 0/1 green Plant creature token
    for each land you control.
    Landfall — Whenever a land enters under your control, you may put a
    +1/+1 counter on each Plant creature you control."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count_selector": "lands_you_control", "power": 0,
                "toughness": 1, "colors": ["G"], "subtypes": ["Plant"],
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {
                "amount": 1, "kind": "+1/+1", "selector": "each_creature_you_control",
                "subtypes": ["Plant"],
            })],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {"subject": "group", "type": "land", "controller": "you"},
            },
            optional=True,
        ),
    ]


register("Avenger of Zendikar", _avenger_of_zendikar)
