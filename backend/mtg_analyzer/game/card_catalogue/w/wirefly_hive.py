
from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _wirefly_hive() -> list[AbilitySpec]:
    '{3}, {T}: Flip a coin. If you win the flip, create a 2/2 colorless Insect artifact creature token with flying named Wirefly. If you lose the flip, destroy all permanents named Wirefly.'
    return [
        AbilitySpec("activated", [EffectSpec("coin_flip", {
            "win_effects": [{"type": "create_token", "params": {
                "token_name": "Wirefly", "count": 1, "power": 2, "toughness": 2, "is_artifact": True,
                "colors": [], "subtypes": ["Insect"], "keywords": ["flying"],
            }}],
            "lose_effects": [{"type": "destroy", "params": {"group": {"zone": "battlefield", "of": "any", "filter": {"name": "Wirefly"}}}}],
        })], cost={"mana": "{3}", "taps_self": True}),
    ]


register('Wirefly Hive', _wirefly_hive)
