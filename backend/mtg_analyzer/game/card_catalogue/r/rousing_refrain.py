from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# Rousing Refrain (ritual off opponent's hand size) — PAR-60
# ===========================================================================
# Reuse of `AddManaEffect` (``target_kind="opponent"`` +
# ``amount_from_target_hand_size``). Suspend folds in from the RULE 702
# keyword catalogue. Documented simplification: "Until end of turn, you
# don't lose this mana as steps and phases end" (an acknowledged engine
# gap) and "Exile Rousing Refrain with three time counters on it" are
# dropped.


def _rousing_refrain() -> list[AbilitySpec]:
    """Add {R} for each card in target opponent's hand. Until end of turn,
    you don't lose this mana as steps and phases end. Exile Rousing Refrain
    with three time counters on it.
    Suspend 3—{1}{R}"""
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("add_mana", {
                "color": "R", "target_kind": "opponent",
                "amount_from_target_hand_size": True,
            })],
        ),
    ]


register("Rousing Refrain", _rousing_refrain)
