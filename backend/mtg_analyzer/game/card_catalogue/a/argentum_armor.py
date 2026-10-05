from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _argentum_armor() -> list[AbilitySpec]:
    """Equipped creature gets +6/+6.
    Whenever equipped creature attacks, destroy target permanent.
    Equip {6}

    — Argentum Armor. Equip is synthesized by the keyword catalogue.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {"affects": "attached_permanent", "power": 6, "toughness": 6})],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("destroy", {"target_kind": "permanent"})],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "attached_permanent"}},
        ),
    ]


register("Argentum Armor", _argentum_armor)
