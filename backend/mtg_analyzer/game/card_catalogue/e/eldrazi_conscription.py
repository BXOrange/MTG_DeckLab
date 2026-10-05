from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _eldrazi_conscription() -> list[AbilitySpec]:
    """Enchant creature
    Enchanted creature gets +10/+10 and has trample and annihilator 2."""
    return [
        AbilitySpec(
            "static",
            [
                EffectSpec("anthem", {"affects": "attached_permanent", "power": 10, "toughness": 10}),
                EffectSpec("grant_keyword", {
                    "affects": "attached_permanent", "keywords": ["trample"],
                    "parametric_keywords": [{"name": "annihilator", "n": 2}],
                }),
            ],
        ),
    ]


register("Eldrazi Conscription", _eldrazi_conscription)
