from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _sword_of_forge_and_frontier() -> list[AbilitySpec]:
    """Equipped creature gets +2/+2 and has protection from red and from green.
    Whenever equipped creature deals combat damage to a player, exile the
    top two cards of your library. You may play those cards this turn. You
    may play an additional land this turn.
    Equip {2}

    — Sword of Forge and Frontier. Protection reads the printed oracle text
    directly (independent of this registry); the "impulsive draw + extra
    land drop" trigger isn't modeled (no "exile and may play until end of
    turn" mechanism exists yet) — a documented gap, only the static pump
    is modeled.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {"affects": "attached_permanent", "power": 2, "toughness": 2})],
        )
    ]


register("Sword of Forge and Frontier", _sword_of_forge_and_frontier)
