from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _rain_of_riches() -> list[AbilitySpec]:
    return [
        AbilitySpec("triggered", [EffectSpec("create_token", {"count": 2, "token_name": "Treasure"})],
                    trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
                    raw_text="when ~ enters, create 2 treasure tokens."),
        AbilitySpec("static", [EffectSpec("grant_keyword", {
            "affects": "spells_you_cast", "keywords": ["cascade"],
            "mana_source_kind": "treasure", "first_matching_each_turn": True,
        })], raw_text="The first spell you cast each turn that mana from a Treasure was spent to cast has cascade."),
    ]


register("Rain of Riches", _rain_of_riches)
