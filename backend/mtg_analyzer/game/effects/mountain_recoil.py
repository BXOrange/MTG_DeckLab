"""Mountain-count damage with rounded-up recoil to the spell's controller."""
from .core import GameEffect, _controller_of
from ..targeting import TargetSpec


class MountainRecoilEffect(GameEffect):
    def __init__(self, source=None):
        super().__init__(source)
        self.target_spec = TargetSpec(kind="opponent_or_planeswalker")

    def apply(self, context, targets=None):
        target = targets[0] if targets else None
        controller = _controller_of(self.source, context)
        if target is None or controller is None:
            return
        x = sum(obj.is_land and obj.has_subtype("Mountain")
                for obj in context.state.permanents_controlled_by(controller.id))
        with context.engine.damage_batch():
            context.engine.deal_damage(target, x, source=self.source)
            context.engine.deal_damage(controller, (x + 1) // 2, source=self.source)
