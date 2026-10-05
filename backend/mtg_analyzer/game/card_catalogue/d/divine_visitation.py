from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _divine_visitation() -> list[AbilitySpec]:
    """If one or more creature tokens would be created under your control, that many 4/4 white Angel creature tokens with flying and vigilance are created instead.

    — Divine Visitation. `substitute_token` with ``from_creature_tokens`` (any creature token, not one
    named token): the same amount of the Angel definition is created in its place.
    """
    return [
        AbilitySpec(
            "replacement",
            [EffectSpec("substitute_token", {
                "from_creature_tokens": True,
                "to": {
                    "token_name": "Angel", "power": 4, "toughness": 4, "colors": ["W"],
                    "subtypes": ["Angel"], "keywords": ["flying", "vigilance"],
                },
            })],
        )
    ]


register("Divine Visitation", _divine_visitation)
