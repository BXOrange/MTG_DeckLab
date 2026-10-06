from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _confiscation_coup() -> list[AbilitySpec]:
    """Choose target artifact or creature. You get {E}{E}{E}{E} (four energy counters), then you may pay an amount of {E} equal to that permanent's mana value. If you do, gain control of it.

    — PLAY-ALL (Living Energy). `add_player_counters`, then `pay_energy_then` with the spell's target (``target_kind``)
    pricing the payment (``amount_from_target_mana_value``) and handed on to the permanent `gain_control_until_eot`
    (``duration="permanent"``, no untap/haste).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("add_player_counters", {"amount": 4, "kind": "energy"}),
                EffectSpec("pay_energy_then", {
                    "target_kind": "artifact_or_creature", "amount_from_target_mana_value": True,
                    "effects": [{"type": "gain_control_until_eot", "params": {
                        "target_kind": "artifact_or_creature", "duration": "permanent", "haste": False, "untap": False,
                    }}],
                }),
            ],
        ),
    ]


register("Confiscation Coup", _confiscation_coup)
