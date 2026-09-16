from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _sword_of_truth_and_justice() -> list[AbilitySpec]:
    """Equipped creature gets +2/+2 and has protection from white and from blue.
    Whenever equipped creature deals combat damage to a player, put a
    +1/+1 counter on a creature you control, then proliferate.
    Equip {2}

    — Sword of Truth and Justice. "put a +1/+1 counter on a creature you
    control" is authored as a real target (``creature_you_control``) rather
    than RULE 701.19's untargeted choice — a small, deliberate simplification
    (functionally equivalent at this engine's fidelity).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {"affects": "attached_permanent", "power": 2, "toughness": 2})],
        ),
        AbilitySpec(
            "triggered",
            [
                EffectSpec("add_counters", {"kind": "+1/+1", "target_kind": "creature_you_control"}),
                EffectSpec("proliferate", {}),
            ],
            trigger={
                "event": EventType.DAMAGE, "condition": {"subject": "attached_permanent"},
                "filter": {"combat": True, "is_player": True},
            },
        ),
    ]


register("Sword of Truth and Justice", _sword_of_truth_and_justice)
