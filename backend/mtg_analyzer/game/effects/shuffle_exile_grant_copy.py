"""Q's library shuffle and exact exiled-card activated-ability grant."""
from .core import GameEffect, EffectRegistry, _controller_of
from ...models.game.game_object import Zone


class ShuffleExileGrantCopyEffect(GameEffect):
    def apply(self, context, targets=None):
        player = _controller_of(self.source, context)
        if player is None:
            return
        context.shuffle_library(player)
        while player.library:
            obj = player.library[-1]
            is_land = obj.card.is_land
            context.engine.exile(obj)
            if is_land:
                continue
            if obj.zone != Zone.EXILE:
                return
            from ..binding.core import bind_ability
            from ...parser.oracle.spec import AbilitySpec, EffectSpec

            spec = AbilitySpec('activated', [EffectSpec('copy_imprinted_card', {
                'from_self': True, 'optional_cast': True,
            })], cost={'text': 'Exile a card from your hand', 'activation_zones': ['exile'],
                      'only_during_your_turn': True},
                raw_text='Exile a card from your hand: Create a copy of this card. You may cast the copy. '
                         'Activate only during your turn and only if this card is exiled.')
            ability = bind_ability(spec, obj)
            ability.granted_zone_incarnation = obj.zone_incarnation
            obj.activated_abilities.append(ability)
            return


EffectRegistry.register('shuffle_exile_grant_copy', lambda p: ShuffleExileGrantCopyEffect())
