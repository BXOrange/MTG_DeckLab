from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _mask_of_memory() -> list[AbilitySpec]:
    """Whenever equipped creature deals combat damage to a player, you may draw two cards. If you do, discard a card.
    Equip {1} ({1}: Attach to target creature you control. Equip only as a sorcery.)

    — PLAY-ALL (Limit Break). An ``attached_permanent`` combat-damage trigger over an `optional` draw two + discard one. Equip is the keyword's.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("optional", {"prompt": "Zwei Karten ziehen und eine abwerfen?", "effects": [
                {"type": "draw", "params": {"count": 2}},
                {"type": "discard", "params": {"count": 1}},
            ]})],
            trigger={
                "event": "DAMAGE", "condition": {"subject": "attached_permanent"},
                "filter": {"combat": True, "is_player": True},
            },
        ),
    ]


register("Mask of Memory", _mask_of_memory)
