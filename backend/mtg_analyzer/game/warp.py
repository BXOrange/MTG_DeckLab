"""Warp delayed exile and persistent casting permission (RULE 702.185)."""
from ..models.game.game_state import DelayedTrigger
from ..models.game.game_object import Zone
from .effects.core import GameEffect


class WarpExileEffect(GameEffect):
    def __init__(self, obj):
        super().__init__(obj)
        self.incarnation = obj.zone_incarnation

    def apply(self, context, targets=None):
        obj = self.source
        # RULE 603.7c: a blinked or departed permanent is a different object.
        if (obj.zone != Zone.BATTLEFIELD or obj.phased_out
                or obj.zone_incarnation != self.incarnation):
            return
        context.engine.exile(obj, warped=True)



def resolve_warp(state, obj, controller_id):
    if not obj.cast_via_warp:
        return
    # RULE 702.185a: exile is independent of who controls the permanent.
    state.delayed_triggers.append(DelayedTrigger(
        controller_id=controller_id, step="end", scope="any",
        effects=[WarpExileEffect(obj)],
        description=f"{obj.name}: Warp — im nächsten Endsegment ins Exil",
    ))
