"""RULE 702.113: the extra target and persistent animation for a paid Awaken cost."""
from .core import GameEffect, StaticAbility
from ..targeting import TargetSpec


class AwakenEffect(GameEffect):
    def __init__(self, count, source):
        super().__init__(source)
        self.count = count
        self.target_spec = TargetSpec(kind="land_you_control")

    def apply(self, context, targets=None):
        if not targets:
            return
        land = targets[0]
        rules = context.engine
        rules.add_counters(land, self.count, "+1/+1", source=self.source)
        for layer, params in (
            ("type", {"add_types": ["creature"], "add_subtypes": ["Elemental"], "power": 0, "toughness": 0}),
            ("ability", {"keywords": ["haste"]}),
        ):
            effect = StaticAbility(
                layer=layer, affects="objects", source=self.source, duration="rest_of_game",
                params={**params, "object_incarnations": {land.instance_id: land.zone_incarnation}},
            )
            effect.object_ids = [land.instance_id]
            effect.timestamp = context.state.next_timestamp()
            context.state.floating_statics.append(effect)
        context.recompute()
