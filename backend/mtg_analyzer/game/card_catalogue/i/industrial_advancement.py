from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _industrial_advancement() -> list[AbilitySpec]:
    """Optional sacrifice followed by a separately optional creature pick."""
    return [AbilitySpec("triggered", [EffectSpec("choose_objects", {
        "action": "sacrifice", "what": "creature", "optional": True,
        "then_that_many": {"measure": "mana_value", "effects": [{
            "type": "inspect_top_choose", "params": {
                "count": "x", "criteria": {"type": "creature"},
                "action": "library_to_battlefield", "optional": True,
                "rest_destination": "library_bottom_random",
            },
        }]},
    })], trigger={"event": "STEP_BEGIN", "filter": {"step": "end"}, "phase_relation": "you"})]


register("Industrial Advancement", _industrial_advancement)
