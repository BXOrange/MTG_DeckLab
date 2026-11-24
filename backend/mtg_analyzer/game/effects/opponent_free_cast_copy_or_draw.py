"""Offer the active opponent one hand cast, then copy it or draw on declining."""
from .core import GameEffect, EffectRegistry, _controller_of
from ..targeting import TargetSpec


class OpponentFreeCastCopyOrDrawEffect(GameEffect):
    def __init__(self, source=None):
        super().__init__(source)
        self.target_spec = TargetSpec(kind='opponent', active_player_only=True)

    def apply(self, context, targets=None):
        controller = _controller_of(self.source, context)
        opponent = targets[0] if targets else None
        if controller is None or opponent is None:
            return
        context.engine._request_resolution_play(
            opponent, list(opponent.hand), zone='hand', free=True, only_spells=True,
            copy_for_player_id=controller.id, draw_if_no_cast_player_id=controller.id,
        )


EffectRegistry.register('opponent_free_cast_copy_or_draw', lambda p: OpponentFreeCastCopyOrDrawEffect())
