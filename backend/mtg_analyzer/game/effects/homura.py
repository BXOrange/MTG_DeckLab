"""Homura's exact-visit death return enters as the flipped enchantment."""
from .core import GameEffect
from ...models.game.game_object import Zone


class HomuraReturnFlippedEffect(GameEffect):
    def apply(self, context, targets=None):
        source=self.source
        visit=context.resolving_source_incarnation
        if (source is None or source.zone!=Zone.GRAVEYARD
                or visit is None or source.zone_incarnation!=visit+1):
            return
        # RULE 400.7 / 710.2: the returning object is already flipped when
        # it enters; it never briefly enters as a creature or fires creature ETBs.
        owner=context.state.player_by_id(source.owner_id)
        context.engine._remove_from_current_zone(owner,source)
        source.reset_as_new_object()
        context.engine._flip_permanent(source, as_enters=True)
        source.controller_id=owner.id
        context.engine._put_searched_card(owner,source,'battlefield')
