"""Split one activation's X damage between its target and its controller."""
from .core import GameEffect, _controller_of
from ..targeting import TargetSpec


class HalfXRecoilEffect(GameEffect):
    def __init__(self, source=None):
        super().__init__(source)
        self.target_spec = TargetSpec(kind="any")

    def apply(self, context, targets=None):
        target = targets[0] if targets else None
        controller = _controller_of(self.source, context)
        if target is None or controller is None:
            return
        # The stack item's announcement survives a later activation with a different X.
        x = max(0, int(getattr(context.resolving_stack_item, "x", 0) or 0))
        if target is controller:
            context.engine.deal_damage(controller, x, source=self.source)
            return
        # Both halves are damage from this source, not a life payment.
        with context.engine.damage_batch():
            context.engine.deal_damage(target, x // 2, source=self.source)
            context.engine.deal_damage(controller, (x + 1) // 2, source=self.source)
