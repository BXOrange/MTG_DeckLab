from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _gatta_and_luzzu() -> list[AbilitySpec]:
    """Flash
    When Gatta and Luzzu enters, choose target creature you control. If damage would be dealt to that creature this turn, prevent that
    damage and put that many +1/+1 counters on it.

    — PLAY-ALL (Counter Blitz). Flash is the keyword's. `prevent_damage_shield` over the chosen creature (``amount`` "all", so it lasts
    the turn) with Vigor's ``add_scaled_counters`` rider on the recipient: one +1/+1 counter per point actually prevented.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("prevent_damage_shield", {
                "target_kind": "creature_you_control", "amount": "all",
                "rider": {"kind": "add_scaled_counters", "on": "recipient", "counter": "+1/+1"},
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Gatta and Luzzu", _gatta_and_luzzu)
