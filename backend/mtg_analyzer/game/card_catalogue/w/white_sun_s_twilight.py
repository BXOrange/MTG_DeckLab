from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _card() -> list[AbilitySpec]:
    return [AbilitySpec("spell_effect", [
        EffectSpec("gain_life", {"amount": "x"}),
        EffectSpec("create_token", {"token_name": "Phyrexian Mite", "count": "x", "power": 1,
            "toughness": 1, "colors": [], "subtypes": ["Phyrexian", "Mite"], "is_artifact": True,
            "parametric_keywords": [{"name": "toxic", "n": 1}], "keywords": ["cant_block"],
            "oracle_text": "Toxic 1\nThis token can't block."}),
        EffectSpec("destroy", {"selector": "all_creatures", "exclude_created": True},
                   condition={"kind": "x_paid", "min": 5}),
    ])]


register("White Sun's Twilight", _card)
