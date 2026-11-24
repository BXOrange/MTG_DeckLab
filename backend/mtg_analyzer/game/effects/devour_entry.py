"""Devour sacrifices happen before the creature enters (RULE 702.82a)."""
from __future__ import annotations

from .core import EffectRegistry, GameEffect, _controller_of


class DevourEntryEffect(GameEffect):
    is_enter_effect = True

    def __init__(self, multiplier: int, visits=None, source=None):
        super().__init__(source)
        self.multiplier = max(0, int(multiplier))
        self.visits = visits

    def apply(self, context, targets=None):
        source = self.source
        if source is None:
            return
        player = _controller_of(source, context)
        if self.visits is None:
            from ..continuous import recompute

            recompute(context.state)
            pool = context.engine._sacrifice_candidates(player, "creature", None, source)
            context.engine._request_choose_objects(
                player, pool, "select_referent", count=len(pool), optional=True, source=source,
                prompt="Wähle Kreaturen für Devour",
                then_specs=[{"type": "devour_entry", "params": {
                    "multiplier": self.multiplier, "visits": {"kind": "chosen_object_visits"},
                }}],
            )
            return

        # RULE 702.82a: choose the entire set, then sacrifice it simultaneously.
        eligible = {obj.instance_id: obj for obj in
                    context.engine._sacrifice_candidates(player, "creature", None, source)}
        victims = [obj for iid, visit in self.visits
                   if (obj := eligible.get(iid)) is not None and obj.zone_incarnation == visit]
        visits = [(obj.instance_id, obj.zone_incarnation) for obj in victims]
        context.engine._sacrifice_simultaneously(victims)
        # RULE 702.82b: only actual departures count, including redirected
        # sacrifices. The engine retains their battlefield characteristics.
        devoured = tuple(visit for visit in visits if visit in context.state.zone_visit_sources)
        source.devoured_creature_visits += devoured
        counters = source.entry_bonus_counters
        if devoured:
            counters["+1/+1"] = counters.get("+1/+1", 0) + self.multiplier * len(devoured)


EffectRegistry.register("devour_entry", lambda p: DevourEntryEffect(p.get("multiplier", 1), p.get("visits")))
