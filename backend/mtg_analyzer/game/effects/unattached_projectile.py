"""Equipment deals damage, then may pass to the damaged creature's controller."""
from .core import GameEffect
from ..control import gain_control
from ..targeting import TargetSpec
from ...models.game.game_object import Zone


class UnattachedProjectileEffect(GameEffect):
    capture_grantor = True
    grantor = None
    grantor_incarnation = None

    def __init__(self, source=None):
        super().__init__(source)
        self.target_spec = TargetSpec(kind="creature")

    def apply(self, context, targets=None):
        target = targets[0] if targets else None
        equipment = self.grantor
        if target is None or equipment is None:
            return
        recipient_id = target.controller_id
        context.engine.deal_damage(target, 2, source=equipment)
        paid = context.trigger_event or {}
        if ("ninja" not in paid.get("unattached_from_subtypes", [])
                and equipment in context.state.permanents()
                and equipment.zone == Zone.BATTLEFIELD
                and equipment.instance_id == paid.get("unattached_source_id")
                and equipment.zone_incarnation == paid.get("unattached_source_incarnation")):
            gain_control(context.state, equipment, recipient_id)
            context.recompute()
