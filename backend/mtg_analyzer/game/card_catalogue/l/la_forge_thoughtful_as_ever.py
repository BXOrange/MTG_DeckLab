from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _la_forge_thoughtful_as_ever() -> list[AbilitySpec]:
    """{T}: For each permanent you control that you've put a counter on this turn, create a 1/1 blue Faerie creature token with flying."""
    return [AbilitySpec("activated", [EffectSpec("create_token", {
        "count": {"kind": "count_selector", "selector": "permanents_you_control_you_put_counters_on_this_turn"},
        "power": 1, "toughness": 1, "colors": ["U"], "subtypes": ["Faerie"],
        "keywords": ["flying"], "token_name": "Faerie",
    })], cost={"text": "{T}"})]


register("La Forge, Thoughtful as Ever", _la_forge_thoughtful_as_ever)
