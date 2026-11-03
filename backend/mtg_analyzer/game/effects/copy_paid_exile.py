"""Copy the card exiled to pay this activation, independent of later payments."""
from __future__ import annotations

from .core import EffectRegistry, GameEffect


class CopyPaidExileEffect(GameEffect):
    def apply(self, context, targets=None):
        from ...models.cards.card import Card
        from ...models.game.game_object import GameObject, Zone

        event = context.trigger_event or {}
        player_id = context.resolving_controller_id or self.source.controller_id
        # RULE 400.7j: the activation keeps the card information captured
        # when its cost was paid, even if that card subsequently moves.
        for data in event.get("cost_exiled_cards") or []:
            prototype = GameObject(Card.from_dict(data), owner_id=player_id, zone=Zone.EXILE)
            context.engine.copy_permanent(player_id, prototype, count=2)


EffectRegistry.register("copy_paid_exile_twice", lambda p: CopyPaidExileEffect())
