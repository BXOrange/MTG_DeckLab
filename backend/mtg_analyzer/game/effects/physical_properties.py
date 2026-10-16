"""Suspend an instruction until a physical printing fact is known."""
from .core import GameEffect
from .. import physical_properties


class MeasurePhysicalPropertyEffect(GameEffect):
    def apply(self, context, targets=None):
        obj = context.revealed_card
        if obj is None or physical_properties.measured(context.state, obj) is not None:
            return
        player_id = context.acting_player_id or getattr(self.source, 'controller_id', None)
        if player_id is not None:
            physical_properties.request(context.engine, obj, player_id)
