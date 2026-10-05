from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _colossus_hammer() -> list[AbilitySpec]:
    """Equipped creature gets +10/+10 and loses flying.
    Equip {8}
    """
    return [
        AbilitySpec(
            "static",
            [
                EffectSpec("anthem", {"affects": "attached_permanent", "power": 10, "toughness": 10}),
                EffectSpec("remove_keyword", {"affects": "attached_permanent", "keywords": ["flying"]}),
            ],
        )
    ]


register("Colossus Hammer", _colossus_hammer)
