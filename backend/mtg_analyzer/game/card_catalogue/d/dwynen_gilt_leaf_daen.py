from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _dwynen_gilt_leaf_daen() -> list[AbilitySpec]:
    """Reach
    Other Elf creatures you control get +1/+1.
    Whenever Dwynen attacks, you gain 1 life for each attacking Elf you
    control.

    — Eliferate deck batch. Reach and the anthem already parse; the attack
    trigger's amount is `continuous.count_selector`'s new
    `attacking_creatures_you_control_of_type_<x>` (`GainLifeEffect.
    count_selector`) — the attacking-scoped sibling of the existing
    `creatures_you_control_of_type_` selector.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("gain_life", {
                "count_selector": "attacking_creatures_you_control_of_type_elf",
            })],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
        ),
    ]


register("Dwynen, Gilt-Leaf Daen", _dwynen_gilt_leaf_daen)
