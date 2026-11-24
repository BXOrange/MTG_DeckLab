"""Two next-spell slots granted by one resolution of Võx's ability."""
from .core import GameEffect, EffectRegistry, _controller_of


class GrantNextUndauntedEffect(GameEffect):
    def apply(self, context, targets=None):
        player = _controller_of(self.source, context)
        if player is not None:
            context.state.next_undaunted_grants.append({
                'player_id': player.id, 'turn': context.state.internal_turn.number,
                'artifact_creature': True, 'spacecraft': True,
            })


EffectRegistry.register('grant_next_undaunted', lambda p: GrantNextUndauntedEffect())
