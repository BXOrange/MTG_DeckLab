from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# Rousing Refrain (ritual off opponent's hand size) — PAR-60
# ===========================================================================
# A `bind` over the target opponent's hand size around `AddManaEffect`
# (``target_kind="opponent"``). Suspend folds in from the RULE 702
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
            [EffectSpec("bind", {
                "name": "n",
                "amount": {"kind": "resource", "resource": "hand_size", "of": "target"},
                "effects": [{"type": "add_mana", "params": {
                    "color": "R", "target_kind": "opponent", "amount": "$n",
                }}],
            })],
        ),
    ]


register("Rousing Refrain", _rousing_refrain)
