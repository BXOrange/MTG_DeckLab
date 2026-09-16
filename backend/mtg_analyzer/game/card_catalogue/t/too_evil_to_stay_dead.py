from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _too_evil_to_stay_dead() -> list[AbilitySpec]:
    """Teamwork 4 (As an additional cost to cast this spell, you may tap
    any number of creatures you control with total power 4 or more.)
    Choose target creature card in your graveyard with mana value 4 or
    less. If this spell was cast using teamwork, instead choose target
    creature card in your graveyard. Return the chosen card to the
    battlefield.

    — MEC-85. Cruel Alliance's own graveyard-target sibling: the same
    `unless_flag="teamwork_paid"` cap-drop, just on `ReturnFromGraveyard
    Effect`'s ``graveyard_creature`` target (own graveyard, RULE
    701.3) instead of `ExileEffect`'s battlefield one — `targeting.
    legal_targets`'s `_GRAVEYARD_TARGET_KINDS` branch reads the very same
    `TargetSpec.max_mana_value` field, so no separate wiring was needed
    there.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("return_from_graveyard", {
                    "target_kind": "graveyard_creature", "destination": "battlefield",
                    "max_mana_value": 4, "unless_flag": "teamwork_paid",
                }),
            ],
        ),
    ]


register("Too Evil to Stay Dead", _too_evil_to_stay_dead)
