"""A targeted Treasure transformation lasting one visit of its source."""
from .core import EffectRegistry
from .counters_tokens import GrantUntilEffect
from dataclasses import replace


class TreasureTransformationEffect(GrantUntilEffect):
    def __init__(self):
        super().__init__(
            target_kind="artifact_or_creature", optional=True,
            duration="for_as_long_as", condition={"kind": "source_on_battlefield"},
            static={"type": "type_change", "params": {"set_types": ["artifact"], "set_subtypes": ["Treasure"]}},
            extra_statics=[
                {"type": "remove_all_abilities", "params": {}},
                {"type": "grant_mana_ability", "params": {
                    "mana": [{"ANY": 1}], "cost": {"taps_self": True, "sacrifice": "self"},
                }},
            ],
        )
        self.target_spec = replace(self.target_spec, per_player="players")


EffectRegistry.register("treasure_transformation_until_source_leaves", lambda p: TreasureTransformationEffect())
