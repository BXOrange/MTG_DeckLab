"""A resolution-local free instant/sorcery cast from an opponent's top cards."""
from .core import GameEffect, EffectRegistry, _controller_of
from ..targeting import TargetSpec
from ...models.game.game_object import Zone


class ExileOpponentTopCastThenBottomEffect(GameEffect):
    def __init__(self, count=0, source=None):
        super().__init__(source)
        self.count = count
        self.target_spec = TargetSpec(kind='opponent')

    def apply(self, context, targets=None):
        controller = _controller_of(self.source, context)
        opponent = targets[0] if targets else None
        if controller is None or opponent is None:
            return
        count = self._measured(self.count, context, targets)
        pool = list(reversed(opponent.library[-count:])) if count > 0 else []
        visits = {}
        for obj in pool:
            context.engine.exile(obj)
            if obj.zone == Zone.EXILE:
                visits[str(obj.instance_id)] = obj.zone_incarnation
        pool = [obj for obj in pool if str(obj.instance_id) in visits]
        # RULE 608.2g: cast at most one now. The remaining cards return
        # before the cast spell resolves, and only from these exile visits.
        context.engine._request_resolution_play(
            controller, pool, free=True, only_spells=True,
            allowed_spell_types=['instant', 'sorcery'],
            bottom_remaining=[obj.instance_id for obj in pool],
            bottom_player_id=opponent.id, bottom_visits=visits,
        )


EffectRegistry.register('exile_opponent_top_cast_then_bottom', lambda p: ExileOpponentTopCastThenBottomEffect(
    count=p.get('count', 0),
))
