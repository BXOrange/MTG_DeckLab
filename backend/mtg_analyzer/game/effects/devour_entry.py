"""Devour sacrifices happen before the creature enters (RULE 702.82a)."""
from __future__ import annotations

from .core import EffectRegistry, GameEffect, _controller_of


class DevourEntryEffect(GameEffect):
    def __init__(self, multiplier=1, sacrificed=None):
        super().__init__()
        self.multiplier = max(0, int(multiplier))
        self.sacrificed = sacrificed

    def apply(self, context, targets=None):
        if self.source is None:
            return
        if self.sacrificed is not None:
            counters = self.source.entry_bonus_creature_counters
            counters["+1/+1"] = counters.get("+1/+1", 0) + self.multiplier * int(self.sacrificed)
            return
        player = _controller_of(self.source, context)
        pool = [obj for obj in context.state.permanents_controlled_by(player.id)
                if obj is not self.source and obj.is_creature and not obj.cant_be_sacrificed_this_turn]
        if pool:
            context.engine._request_choose_objects(
                player, pool, "sacrifice", count=len(pool), optional=True, source=self.source,
                prompt="Wähle Kreaturen für Devour",
                then_that_many={"effects": [{"type": "devour_entry", "params": {
                    "multiplier": self.multiplier, "sacrificed": "x",
                }}]},
            )


EffectRegistry.register("devour_entry", lambda p: DevourEntryEffect(p.get("multiplier", 1), p.get("sacrificed")))
