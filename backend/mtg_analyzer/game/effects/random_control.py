"""Random assignment of nonland permanents, followed by control and untap."""
from __future__ import annotations

from .core import GameEffect
from ..control import gain_control


class RandomNonlandControlEffect(GameEffect):
    def apply(self, context, targets=None):
        players = [player for player in context.state.players if not player.has_lost]
        if not players:
            return
        # Capture every assignment before changing control or firing untap events.
        assignments = [
            (obj, context.engine.random_choice(players).id)
            for obj in context.state.permanents() if not obj.is_land
        ]
        # RULE 611.2a: no duration is stated, so these control effects persist.
        for obj, player_id in assignments:
            gain_control(context.state, obj, player_id)
        context.recompute()
        for obj, _ in assignments:
            context.set_tapped(obj, False)
