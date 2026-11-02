
from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _old_rutstein() -> list[AbilitySpec]:
    'When Old Rutstein enters and at the beginning of your upkeep, mill a card. If a land card is milled this way, create a Treasure token. If a creature card is milled this way, create a 1/1 green Insect creature token. If a noncreature, nonland card is milled this way, create a Blood token.'
    triggers = [
        {"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        {"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"}, "phase_relation": "you"},
    ]
    result = []
    for trigger in triggers:
        land = {"kind": "this_way_pool", "pool": "milled", "card_type": "land"}
        creature = {"kind": "this_way_pool", "pool": "milled", "card_type": "creature"}
        result.append(AbilitySpec("triggered", [
            EffectSpec("mill", {"count": 1}),
            EffectSpec("if_else", {"condition": land, "then": [{"type": "create_token", "params": {"token_name": "Treasure"}}]}),
            EffectSpec("if_else", {"condition": creature, "then": [{"type": "create_token", "params": {
                "token_name": "Insect", "power": 1, "toughness": 1, "colors": ["G"], "subtypes": ["Insect"],
            }}]}),
            EffectSpec("if_else", {"condition": {"kind": "all", "conditions": [
                {"kind": "this_way_pool", "pool": "milled"},
                {"kind": "not", "condition": land}, {"kind": "not", "condition": creature},
            ]}, "then": [{"type": "create_token", "params": {"token_name": "Blood"}}]}),
        ], trigger=trigger))
    return result



register('Old Rutstein', _old_rutstein)
