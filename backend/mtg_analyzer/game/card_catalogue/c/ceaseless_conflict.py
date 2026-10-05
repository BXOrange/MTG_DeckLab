from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _ceaseless_conflict() -> list[AbilitySpec]:
    """Destroy all creatures. Then create a 3/2 red and white Spirit creature
    token for each nontoken creature you controlled that was destroyed this
    way.

    Documented simplification: the token count is *every* creature destroyed
    (`permanents_destroyed_this_way`), not just your nontoken ones."""
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("destroy", {"selector": "all_creatures"}),
                EffectSpec("create_token", {
                    "token_name": "Spirit", "power": 3, "toughness": 2,
                    "colors": ["R", "W"], "subtypes": ["Spirit"],
                    "count_from_context": "permanents_destroyed_this_way",
                }),
            ],
        ),
    ]


register("Ceaseless Conflict", _ceaseless_conflict)
