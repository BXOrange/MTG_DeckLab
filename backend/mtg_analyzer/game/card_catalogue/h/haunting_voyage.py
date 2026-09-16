from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _haunting_voyage() -> list[AbilitySpec]:
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("_request_choose_creature_type_grant", {"then_specs": [
                {"type": "return_chosen_creature_type_from_graveyard", "params": {}},
            ]})],
        ),
        AbilitySpec("keyword", [], keyword={"name": "foretell", "cost": "{5}{B}{B}"}),
    ]


register("Haunting Voyage", _haunting_voyage)
