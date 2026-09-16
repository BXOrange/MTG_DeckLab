from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _worst_fears() -> list[AbilitySpec]:
    """You control target player during that player's next turn. Exile
    Worst Fears.

    — MEC-51 (RULE 720), same `control_player` primitive as Mindslaver, see
    `card_catalogue/m/mindslaver.py`.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("control_player", {"scope": "turn", "target_kind": "player"}),
                EffectSpec("exile", {"target_kind": None}),
            ],
        ),
    ]


register("Worst Fears", _worst_fears)
