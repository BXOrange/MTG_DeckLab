from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _sages_reverie() -> list[AbilitySpec]:
    """Enchant creature
    When this Aura enters, draw a card for each Aura you control that's
    attached to a creature.
    Enchanted creature gets +1/+1 for each Aura you control that's attached
    to a creature."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"amount_from_count_selector": "auras_you_control"})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {
                "affects": "attached_permanent", "power": 1, "toughness": 1,
                "power_count": "auras_you_control", "toughness_count": "auras_you_control",
            })],
        ),
    ]


register("Sage's Reverie", _sages_reverie)
