from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _stridehangar_automaton() -> list[AbilitySpec]:
    """Thopters you control get +1/+1.
    If one or more artifact tokens would be created under your control, those tokens plus an additional 1/1 colorless Thopter artifact creature token with flying are created instead.

    — PLAY-ALL (Living Energy). The anthem is the parser's. The replacement is Chatterfang's
    `additional_creature_tokens` with ``only_artifact`` and ``fixed_amount`` 1 (one extra Thopter per creation).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {"power": 1, "toughness": 1, "affects": "creatures_you_control", "subtype": "Thopter"})],
        ),
        AbilitySpec(
            "replacement",
            [EffectSpec("additional_creature_tokens", {
                "token_name": "Thopter", "power": 1, "toughness": 1, "colors": [], "subtypes": ["Thopter"],
                "keywords": ["flying"], "is_artifact": True, "only_artifact": True, "fixed_amount": 1,
            })],
        ),
    ]


register("Stridehangar Automaton", _stridehangar_automaton)
