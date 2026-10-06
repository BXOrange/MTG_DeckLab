from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _card() -> list[AbilitySpec]:
    # Mana production is bound from oracle text; RULE 111 governs the token.
    return [AbilitySpec("activated", [EffectSpec("create_token", {
        "token_name": "Kobolds of Kher Keep", "power": 0, "toughness": 1,
        "colors": ["R"], "subtypes": ["Kobold"], "count": 1,
    })], cost={"mana": "{1}{R}", "taps_self": True})]


register('Kher Keep', _card)
