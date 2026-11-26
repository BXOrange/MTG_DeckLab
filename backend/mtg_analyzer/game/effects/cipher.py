"""RULE 702.99: encode a resolving spell card, then copy it on combat damage."""
from .core import GameEffect, _controller_of
from ...models.game.game_object import GameObject, Zone


class EncodeCipherEffect(GameEffect):
    def apply(self, context, targets=None):
        card = self.source
        if getattr(card, "is_copy", False) or card.is_token or card.zone != Zone.STACK:
            return
        player = _controller_of(card, context)
        creatures = [obj for obj in context.state.permanents_controlled_by(player.id) if obj.is_creature]
        if not creatures:
            return
        context.state.pending_cipher_source = card
        context.engine.open_choice({
            "kind": "cipher_encode", "player_id": player.id,
            "prompt": f"{card.name}: Cipher",
            "visits": {str(obj.instance_id): obj.zone_incarnation for obj in creatures},
            "options": [{"id": str(obj.instance_id), "label": obj.name} for obj in creatures]
                       + [{"id": "decline", "label": "Decline"}],
        })


class CopyEncodedCardEffect(GameEffect):
    def __init__(self, card, source):
        super().__init__(source)
        self.card_id = card.instance_id
        self.visit = card.zone_incarnation

    def apply(self, context, targets=None):
        from ..binding.core import bind_from_catalogue

        card = context.state.find_object(self.card_id)
        if card is None or card.zone != Zone.EXILE or card.zone_incarnation != self.visit:
            return
        player = _controller_of(self.source, context)
        copied = GameObject(card.card.as_copy(), owner_id=player.id, zone=Zone.EXILE)
        copied.is_copy = True
        bind_from_catalogue(copied)
        player.add_to_zone(copied, Zone.EXILE)
        context.engine._request_resolution_play(player, [copied], free=True, only_spells=True)
