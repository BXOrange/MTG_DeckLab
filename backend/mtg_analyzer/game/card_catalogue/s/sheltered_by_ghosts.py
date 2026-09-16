from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _sheltered_by_ghosts() -> list[AbilitySpec]:
    """Enchant creature you control
    When this Aura enters, exile target nonland permanent an opponent
    controls until this Aura leaves the battlefield.
    Enchanted creature gets +1/+0 and has lifelink and ward {2}."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("exile", {
                "target_kind": "nonland_permanent_you_dont_control",
                "remember": True, "until_source_leaves": True,
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("return_linked_exile", {})],
            trigger={"event": EventType.LEAVES_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "static",
            [
                EffectSpec("anthem", {"affects": "attached_permanent", "power": 1, "toughness": 0}),
                EffectSpec("grant_keyword", {
                    "affects": "attached_permanent", "keywords": ["lifelink"], "ward_cost": "{2}",
                }),
            ],
        ),
    ]


register("Sheltered by Ghosts", _sheltered_by_ghosts)
