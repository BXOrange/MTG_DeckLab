"""A chosen permanent's additional trigger, bounded by the source remaining tapped."""
from __future__ import annotations

from .core import GameEffect, EffectRegistry
from .exile_control import TriggerDoublerEffect
from ..targeting import TargetSpec
from .. import durations
from ...models.game.game_object import Zone


class GrantBoundTriggerDoublerEffect(GameEffect):
    def __init__(self, source=None):
        super().__init__(source)
        self.target_spec=TargetSpec(kind='creature_you_control', exclude_source=True)

    def apply(self, context, targets=None):
        target=(targets or [None])[0]
        source=self.source
        visit=context.resolving_source_incarnation
        if (target is None or target.zone!=Zone.BATTLEFIELD or source is None
                or source.zone!=Zone.BATTLEFIELD or not source.tapped
                or (visit is not None and source.zone_incarnation!=visit)):
            return
        marker=TriggerDoublerEffect(source=source)
        durations.stamp(marker,context,source,'for_as_long_as',{'kind':'source_tapped'},affected=target)
        context.state.floating_statics.append(marker)
        context.recompute()


EffectRegistry.register('grant_bound_trigger_doubler',lambda p: GrantBoundTriggerDoublerEffect())
