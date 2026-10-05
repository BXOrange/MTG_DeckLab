from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _chains_of_custody() -> list[AbilitySpec]:
    """Enchant creature you control
    When this Aura enters, exile target nonland permanent an opponent
    controls until this Aura leaves the battlefield.
    Enchanted creature has ward {2}."""
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
            [EffectSpec("grant_keyword", {"affects": "attached_permanent", "ward_cost": "{2}"})],
        ),
    ]


register("Chains of Custody", _chains_of_custody)
