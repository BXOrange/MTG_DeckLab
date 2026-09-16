from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _distant_melody() -> list[AbilitySpec]:
    return [AbilitySpec("spell_effect", [
        EffectSpec("_request_choose_creature_type_grant", {"then_specs": [
            {"type": "draw_controlled_chosen_creature_type", "params": {}},
        ]}),
    ])]


register("Distant Melody", _distant_melody)
