from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _the_battle_of_bywater() -> list[AbilitySpec]:
    """Destroy all creatures with power 3 or greater. Then create a Food
    token for each creature you control.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("destroy", {"selector": "all_creatures", "filter": {"min_power": 3}}),
                EffectSpec("create_token", {"token_name": "Food", "count_selector": "creatures_you_control"}),
            ],
        ),
    ]


register("The Battle of Bywater", _the_battle_of_bywater)
