from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _hangarback_walker() -> list[AbilitySpec]:
    """This creature enters with X +1/+1 counters on it.
    When this creature dies, create a 1/1 colorless Thopter artifact creature
    token with flying for each +1/+1 counter on this creature.
    {1}, {T}: Put a +1/+1 counter on this creature."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "token_name": "Thopter", "power": 1, "toughness": 1, "colors": [],
                "subtypes": ["Thopter"], "keywords": ["flying"], "artifact": True,
                "count_from_trigger_event_counter": "+1/+1",
            })],
            trigger={"event": EventType.DIES, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("add_counters", {"count": 1, "kind": "+1/+1"})],
            cost={"mana": "{1}", "taps_self": True},
        ),
    ]


register("Hangarback Walker", _hangarback_walker)
