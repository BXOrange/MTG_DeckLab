from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _shielded_by_faith() -> list[AbilitySpec]:
    """Enchant creature
    Enchanted creature has indestructible.
    Whenever a creature enters, you may attach this Aura to that creature."""
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {
                "affects": "attached_permanent", "keywords": ["indestructible"],
            })],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("attach_triggering_permanent", {})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject_type": "creature"}},
            optional=True,
        ),
    ]


register("Shielded by Faith", _shielded_by_faith)
