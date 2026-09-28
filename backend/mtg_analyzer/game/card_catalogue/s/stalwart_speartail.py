from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _stalwart_speartail() -> list[AbilitySpec]:
    """Enrage — Whenever Stalwart Speartail is dealt damage, other
    Dinosaurs you control and Dinosaur cards in your hand and library
    perpetually get +1/+1.
    Whenever Stalwart Speartail attacks, Stalwart Speartail deals 1 damage
    to each creature and each planeswalker.

    The enrage trigger is MEC-98's perpetual pump: ``card_zones`` reaches
    the Dinosaur cards in hand and library, ``selector`` the other Dinosaurs
    on the battlefield, ``subtypes`` narrows both.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("pump", {
                "power": 1, "toughness": 1, "perpetual": True,
                "selector": "other_creatures_you_control",
                "card_zones": ["hand", "library"], "subtypes": ["dinosaur"],
            })],
            trigger={"event": "DAMAGE", "condition": {"subject": "self", "recipient": True}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"amount": 1, "selector": "each_creature_and_planeswalker"})],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
        ),
    ]


register("Stalwart Speartail", _stalwart_speartail)
