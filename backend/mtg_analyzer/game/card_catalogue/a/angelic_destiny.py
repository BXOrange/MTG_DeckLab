from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _angelic_destiny() -> list[AbilitySpec]:
    """Enchant creature
    Enchanted creature gets +4/+4, has flying and first strike, and is an
    Angel in addition to its other types.
    When enchanted creature dies, return this card to its owner's hand."""
    return [
        AbilitySpec(
            "static",
            [
                EffectSpec("anthem", {"affects": "attached_permanent", "power": 4, "toughness": 4}),
                EffectSpec("grant_keyword", {
                    "affects": "attached_permanent", "keywords": ["flying", "first strike"],
                }),
                EffectSpec("type_change", {
                    "affects": "attached_permanent", "add_subtypes": ["Angel"],
                }),
            ],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("return_to_hand", {"target_kind": None})],
            trigger={"event": EventType.DIES, "condition": {"subject": "attached_permanent"}},
        ),
    ]


register("Angelic Destiny", _angelic_destiny)
