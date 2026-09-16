from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _bloodforged_battle_axe() -> list[AbilitySpec]:
    """Equipped creature gets +2/+0.
    Whenever equipped creature deals combat damage to a player, create a
    token that's a copy of this Equipment.
    Equip {2}
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {"affects": "attached_permanent", "power": 2, "toughness": 0})],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("copy_permanent", {"target_kind": None})],
            trigger={
                "event": EventType.DAMAGE, "condition": {"subject": "attached_permanent"},
                "filter": {"combat": True, "is_player": True},
            },
        ),
    ]


register("Bloodforged Battle-Axe", _bloodforged_battle_axe)
