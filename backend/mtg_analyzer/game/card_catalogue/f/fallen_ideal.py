from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _fallen_ideal() -> list[AbilitySpec]:
    """Enchant creature
    Enchanted creature has flying and "Sacrifice a creature: This creature
    gets +2/+1 until end of turn."
    When this Aura is put into a graveyard from the battlefield, return it to
    its owner's hand."""
    return [
        AbilitySpec(
            "static",
            [
                EffectSpec("grant_keyword", {"affects": "attached_permanent", "keywords": ["flying"]}),
                EffectSpec("grant_activated_ability", {
                    "affects": "attached_permanent",
                    "cost": {"text": "Sacrifice a creature"},
                    "grant_effects": [{"type": "pump", "params": {"power": 2, "toughness": 1}}],
                }),
            ],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("return_to_hand", {"target_kind": None})],
            trigger={"event": EventType.DIES, "condition": {"subject": "self"}},
        ),
    ]


register("Fallen Ideal", _fallen_ideal)
