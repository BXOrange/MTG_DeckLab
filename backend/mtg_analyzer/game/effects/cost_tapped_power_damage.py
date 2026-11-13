"""Damage measured from the exact creature tapped to pay this activation."""
from .core import GameEffect
from ..targeting import TargetSpec
from ...models.game.game_object import Zone


class CostTappedPowerDamageEffect(GameEffect):
    def __init__(self, source=None):
        super().__init__(source)
        self.target_spec = TargetSpec(kind="creature", creature_filter={
            "attacking_or_blocking": True, "keyword": "flying",
        })

    def apply(self, context, targets=None):
        victim = targets[0] if targets else None
        visits = (context.trigger_event or {}).get("cost_tapped_visits") or []
        if victim is None or not visits:
            return
        visit = visits[0]
        obj = context.state.find_object(visit["instance_id"])
        if obj is not None and obj.zone == Zone.BATTLEFIELD and obj.zone_incarnation == visit["zone_incarnation"]:
            power = obj.power
        else:
            # RULE 608.2h: a departed creature uses its last battlefield power.
            power = context.state.zone_visit_characteristics.get(
                (visit["instance_id"], visit["zone_incarnation"]), {}).get("power", 0)
        context.engine.deal_damage(victim, max(0, int(power or 0)), source=self.source)
