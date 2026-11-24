"""A turn-scoped prohibition on a player declaring attackers."""
from .core import GameEffect, EffectRegistry


class PlayerCantAttackThisTurnEffect(GameEffect):
    def apply(self, context, targets=None):
        player=self._operand_player(context,targets,{'of':'event_player'})
        if player is not None:
            context.state.players_cant_attack_this_turn.add(player.id)


EffectRegistry.register('player_cant_attack_this_turn',lambda p: PlayerCantAttackThisTurnEffect())
