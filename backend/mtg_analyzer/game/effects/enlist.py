"""The triggered half of an Enlist attack cost (RULE 702.154)."""

from .. import continuous
from .counters_tokens import PumpEffect
from .core import GameEffect


class EnlistEffect(GameEffect):
    def __init__(self, source, enlisted, power: int):
        super().__init__(source)
        self.enlisted_visit = (enlisted.instance_id, enlisted.zone_incarnation)
        self.power_at_enlist = power

    def apply(self, context, targets=None):
        # RULE 608.2h: read power at resolution, with last known information
        # if the enlisted creature left its original battlefield visit.
        state = context.state
        iid, incarnation = self.enlisted_visit
        enlisted = state.find_object(iid)
        if enlisted in state.battlefield and enlisted.zone_incarnation == incarnation:
            continuous.recompute(state)
            power = enlisted.power
        else:
            power = state.zone_visit_characteristics.get(self.enlisted_visit, {}).get("power", self.power_at_enlist)
        PumpEffect(power=int(power or 0), source=self.source).apply(context)
