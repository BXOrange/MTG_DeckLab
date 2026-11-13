"""Eriette anchors her control effect to the firing Aura's attachment visit."""
from .core import GameEffect, _controller_of
from .exile_control import GainControlUntilEndOfTurnEffect
from ...models.game.game_object import Zone


class ErietteAttachmentControlEffect(GameEffect):
    def apply(self, context, targets=None):
        event=context.trigger_event or {}
        aura=context.state.find_object(event.get('instance_id'))
        host=context.state.find_object(event.get('target_id'))
        controller=_controller_of(self.source,context)
        if (aura is None or host is None or controller is None
                or aura.zone!=Zone.BATTLEFIELD or host.zone!=Zone.BATTLEFIELD
                or aura.zone_incarnation!=event.get('attachment_incarnation')
                or host.zone_incarnation!=event.get('target_incarnation')):
            return
        effect=GainControlUntilEndOfTurnEffect(source=aura, target_kind=None,
            haste=False, untap=False, condition={
                'kind':'source_attached_to_affected',
                'attachment_generation':event.get('attachment_generation'),
            })
        # RULE 611.2b: the duration belongs to the Aura, not Eriette. It must
        # already hold when this trigger resolves, and never restart later.
        outer=context.resolving_source_incarnation
        context.resolving_source_incarnation=aura.zone_incarnation
        try:
            effect._take(context,host,controller)
            context.recompute()
        finally:
            context.resolving_source_incarnation=outer
