from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _garruks_uprising() -> list[AbilitySpec]:
    """When this enchantment enters, if you control a creature with power 4
    or greater, draw a card.
    Creatures you control have trample."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1}, condition={"controls_creature_power_at_least": 4})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {"affects": "creatures_you_control", "keywords": ["trample"]})],
        ),
    ]


register("Garruk's Uprising", _garruks_uprising)
