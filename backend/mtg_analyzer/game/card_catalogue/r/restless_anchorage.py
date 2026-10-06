from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _card() -> list[AbilitySpec]:
    # RULE 613: animation, color and flying occupy their respective layers.
    return [
        AbilitySpec("activated", [
            EffectSpec("grant_until", {"target_kind": None, "duration": "end_of_turn", "static": {
                "type": "type_change", "params": {"add_types": ["creature"], "add_subtypes": ["Bird"],
                                                  "power": 2, "toughness": 3}}}),
            EffectSpec("grant_until", {"target_kind": None, "duration": "end_of_turn", "static": {
                "type": "color_change", "params": {"colors": ["W", "U"], "set": True}}}),
            EffectSpec("grant_until", {"target_kind": None, "duration": "end_of_turn", "static": {
                "type": "grant_keyword", "params": {"keywords": ["flying"]}}}),
        ], cost={"mana": "{1}{W}{U}"}),
        AbilitySpec("triggered", [EffectSpec("create_token", {"token_name": "Map", "count": 1})],
                    trigger={"event": "ATTACKS", "condition": {"subject": "self"}}),
    ]


register('Restless Anchorage', _card)
