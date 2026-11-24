"""Reciprocal private library-top exile and standing play permissions."""
from .core import GameEffect, EffectRegistry, _controller_of
from ..targeting import TargetSpec
from ...models.game.game_object import Zone


class ExchangeTopLibraryPermissionsEffect(GameEffect):
    def __init__(self, own_count=1, opponent_count=2, source=None):
        super().__init__(source)
        self.target_spec = TargetSpec(kind='opponent')
        self.own_count = own_count
        self.opponent_count = opponent_count

    def apply(self, context, targets=None):
        controller = _controller_of(self.source, context)
        opponent = targets[0] if targets else None
        if controller is None or opponent is None:
            return
        for library_owner, exiler, count in (
            (controller, opponent, self.own_count),
            (opponent, controller, self.opponent_count),
        ):
            # RULE 406.3: looking before face-down exile allows that same
            # player to keep looking throughout this exact exile visit.
            cards = list(reversed(library_owner.library[-count:])) if count > 0 else []
            for obj in cards:
                context.engine.exile(obj, face_down=True, face_down_viewers={exiler.id})
                if obj.zone != Zone.EXILE:
                    continue
                context.engine._grant_temp_play_permission(
                    obj, exiler, self.source.name if self.source else None,
                    same_turn_only=False, mana_wildcard='type',
                )
                context.state.temp_play_permission_standing.add(obj.instance_id)
                context.created_objects.append(obj)


EffectRegistry.register('exchange_top_library_permissions', lambda p: ExchangeTopLibraryPermissionsEffect(
    own_count=int(p.get('own_count', 1)), opponent_count=int(p.get('opponent_count', 2)),
))
