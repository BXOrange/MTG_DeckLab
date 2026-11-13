"""Tap the first creature; if successful, it deals its power to the second."""
from .core import GameEffect
from ..targeting import TargetSpec


class TapCreatureStrikeEffect(GameEffect):
    def __init__(self, source=None):
        super().__init__(source)
        self.target_spec = TargetSpec(kind="creature_you_control", creature_filter={"tapped": False})
        self.extra_target_specs = (TargetSpec(
            kind="creature_you_dont_control", creature_filter={"attacking_or_blocking": True},
        ),)

    def apply(self, context, targets=None):
        dealer, victim = (list(targets or []) + [None, None])[:2]
        if dealer is None or dealer.tapped:
            return
        context.engine.set_tapped(dealer, True)
        if not dealer.tapped or victim is None:
            return
        context.recompute()
        context.engine.deal_damage(victim, max(0, int(dealer.power or 0)), source=dealer)
