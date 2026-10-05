from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _arachnogenesis() -> list[AbilitySpec]:
    """Create X 1/2 green Spider creature tokens with reach, where X is the number of creatures
    attacking you. Prevent all combat damage that would be dealt this turn by non-Spider creatures.

    — Tramplesaurus Rex deck batch. Galadhrim Ambush's shape: `create_token` counted by the new
    ``creatures_attacking_you`` selector (attackers whose declared defender is the controller), then
    `prevent_all_combat_damage` with its ``exclude_subtype`` qualifier so the new Spiders still deal
    damage (RULE 615).
    """
    return [
        AbilitySpec("spell_effect", [
            EffectSpec("create_token", {
                "colors": ["G"], "subtypes": ["Spider"], "keywords": ["reach"], "token_name": "Spider",
                "power": 1, "toughness": 2, "count_selector": "creatures_attacking_you",
            }),
            EffectSpec("prevent_all_combat_damage", {"exclude_subtype": "spider"}),
        ]),
    ]


register("Arachnogenesis", _arachnogenesis)
