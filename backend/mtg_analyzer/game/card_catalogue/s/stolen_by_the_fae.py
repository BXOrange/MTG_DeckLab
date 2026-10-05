from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _stolen_by_the_fae() -> list[AbilitySpec]:
    """Return target creature with mana value X to its owner's hand. You create X 1/1 blue Faerie creature
    tokens with flying.

    — Family Matters deck batch. `return_to_hand` with the new ``exact_mana_value: "x"`` target ceiling
    (the announced {X}, `TargetSpec.exact_mana_value`) and a `create_token` whose count is that same X.
    """
    return [
        AbilitySpec("spell_effect", [
            EffectSpec("return_to_hand", {"target_kind": "creature", "exact_mana_value": "x"}),
            EffectSpec("create_token", {
                "count": "x", "power": 1, "toughness": 1, "colors": ["U"], "subtypes": ["Faerie"],
                "keywords": ["flying"], "token_name": "Faerie",
            }),
        ]),
    ]


register("Stolen by the Fae", _stolen_by_the_fae)
