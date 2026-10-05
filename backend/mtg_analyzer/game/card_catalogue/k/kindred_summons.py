from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _kindred_summons() -> list[AbilitySpec]:
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("_request_choose_creature_type_grant", {"then_specs": [
                {"type": "kindred_summons", "params": {}},
            ]})],
        ),
    ]


register("Kindred Summons", _kindred_summons)
