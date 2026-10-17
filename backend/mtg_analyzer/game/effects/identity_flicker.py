"""Last battlefield copiable values survive the exile instruction."""
from .core import GameEffect, _controller_of
from .flicker_composites import _exile_batch
from .conditional_flicker import ReturnCapturedExileVisitsEffect
from ..targeting import TargetSpec
from ...models.game.game_object import GameObject, Zone
from ...models.game.game_state import DelayedTrigger


class IdentityFlickerEffect(GameEffect):
    def __init__(self, source=None):
        super().__init__(source)
        self.target_spec = TargetSpec(kind='creature', creature_filter={'nontoken': True})

    def apply(self, context, targets=None):
        if not targets:
            return
        target = targets[0]
        # RULE 608.2h/707.2: capture the shown face and copy effects before
        # exile restores the physical card's original printed identity.
        copiable = target.card.as_copy()
        visits = _exile_batch(context, [target])
        if not visits:
            return
        player = _controller_of(self.source, context)
        expected = context.resolving_source_incarnation
        if (self.source.zone == Zone.BATTLEFIELD and
                (expected is None or self.source.zone_incarnation == expected)):
            proxy = GameObject(copiable, owner_id=target.owner_id, zone=Zone.BATTLEFIELD)
            context.engine.become_copy_until_end_of_turn(self.source, proxy)
        context.state.delayed_triggers.append(DelayedTrigger(
            player.id, 'end', [ReturnCapturedExileVisitsEffect(visits, source=self.source)], scope='any'))
